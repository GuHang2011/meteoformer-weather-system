import time
from pathlib import Path

import numpy as np

from .data import CHANNELS, HISTORY, HORIZON, constrain, read_grid, split_info, tensor_data


def metrics(pred, truth, climate):
    result = {}
    for c, name in enumerate(CHANNELS):
        p, t = pred[:, c], truth[:, c]
        ap, at = p - climate[c], t - climate[c]
        denom = np.sqrt(np.sum(ap ** 2) * np.sum(at ** 2))
        result[name] = {'rmse': float(np.sqrt(np.mean((p - t) ** 2))),
                        'mae': float(np.mean(np.abs(p - t))),
                        'acc': float(np.sum(ap * at) / denom) if denom > 1e-8 else None}
    p, t = pred[:, 4] >= 1, truth[:, 4] >= 1
    hit, miss, false = int((p & t).sum()), int((~p & t).sum()), int((p & ~t).sum())
    result['precipitation'] = {'threshold_mm': 1, 'hits': hit, 'misses': miss, 'false_alarms': false,
                              'csi': hit / (hit + miss + false) if hit + miss + false else None,
                              'pod': hit / (hit + miss) if hit + miss else None,
                              'far': false / (hit + false) if hit + false else None}
    return result


def crps(ensemble, truth):
    return float(np.mean(np.abs(ensemble - truth)) - .5 * np.mean(np.abs(ensemble[:, None] - ensemble[None, :])))


def validate_model_dataset(store, job, dataset):
    """Permit new initial fields only on the trained source and exact coordinate grid."""
    original = store.get(job['dataset_id'], 'dataset')
    if original['source'] != dataset['source']:
        raise ValueError('初值数据与模型训练数据的来源不一致，不可混用演示资料与真实资料')
    if original['shape'] != dataset['shape'] or original['bounds'] != dataset['bounds']:
        raise ValueError('初值网格尺寸或覆盖范围与训练网格不一致，请采用相同区域及重采样尺寸')
    if original['id'] != dataset['id']:
        with read_grid(store.root / 'datasets' / (original['id'] + '.zarr')) as trained, \
             read_grid(store.root / 'datasets' / (dataset['id'] + '.zarr')) as incoming:
            if not all(np.allclose(trained[c], incoming[c], rtol=0, atol=1e-6) for c in ('lat', 'lon')):
                raise ValueError('初值与训练网格坐标不一致')
            if incoming.time.values[-1] < trained.time.values[-1]:
                raise ValueError('新起报资料的结束时间不能早于模型资料结束时间，以避免前视偏差')


def train(store, job_id, dataset, epochs, samples):
    try:
        import torch
        from .model import MeteoFormer, weather_loss
        torch.set_num_threads(2)
        torch.manual_seed(42)
        started = time.perf_counter()
        store.update(job_id, status='running', message='加载数据并按时间分区')
        with read_grid(store.root / 'datasets' / (dataset['id'] + '.zarr')) as ds:
            raw = tensor_data(ds)
        partitions = split_info(len(raw))
        if min(b - a for a, b in partitions.values()) < HISTORY + HORIZON:
            raise ValueError('验证集和测试集各需至少 36 小时，建议上传至少 240 小时数据')
        if any(n % 8 for n in raw.shape[-2:]):
            raise ValueError('训练网格边长必须是 8 的倍数，请导入时重采样到 16 / 32 / 64')
        a, b = partitions['train']
        mean = raw[a:b].mean(axis=(0, 2, 3), keepdims=True)
        std = np.maximum(raw[a:b].std(axis=(0, 2, 3), keepdims=True), .1)
        climate = raw[a:b].mean(axis=0)
        normalized = (raw - mean) / std

        def starts(part, maximum):
            lo, hi = partitions[part]
            total = hi - lo - HISTORY - HORIZON + 1
            return np.unique(np.linspace(lo, hi - HISTORY - HORIZON, min(maximum, total), dtype=int))

        training_starts = starts('train', samples)
        val_starts = starts('validation', 4)
        test_starts = starts('test', 4)
        model = MeteoFormer()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=.01)
        schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
        logs, best, stale = [], float('inf'), 0
        best_state = None
        previous_horizon = None
        for epoch in range(epochs):
            horizon = (1 if epoch < epochs // 3 else 6 if epoch < 2 * epochs // 3 else 24)
            if horizon != previous_horizon:
                best, stale, best_state = float('inf'), 0, None
                previous_horizon = horizon
            model.train()
            losses = []
            for start in training_starts:
                x = torch.from_numpy(normalized[start:start + HISTORY][None])
                y = torch.from_numpy(normalized[start + HISTORY:start + HISTORY + horizon][None])
                optimizer.zero_grad()
                loss = weather_loss(model(x, horizon), y)
                if not torch.isfinite(loss):
                    raise ValueError('训练损失非有限值，任务已停止')
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.)
                optimizer.step()
                losses.append(loss.item())
            model.eval()
            with torch.no_grad():
                val = [weather_loss(model(torch.from_numpy(normalized[s:s + HISTORY][None]), horizon),
                                    torch.from_numpy(normalized[s + HISTORY:s + HISTORY + horizon][None])).item()
                       for s in val_starts]
            score = float(np.mean(val))
            if not np.isfinite(score):
                raise ValueError('验证损失非有限值，任务已停止')
            if score < best:
                best, stale = score, 0
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            else:
                stale += 1
            schedule.step()
            logs.append({'epoch': epoch + 1, 'horizon': horizon, 'loss': float(np.mean(losses)),
                         'validation_loss': score, 'elapsed_seconds': round(time.perf_counter() - started, 2)})
            store.update(job_id, epoch=epoch + 1, progress=round((epoch + 1) / epochs * 100), logs=logs,
                         message=f'第 {epoch + 1}/{epochs} 轮，预测时效 {horizon} 小时')
            if horizon == 24 and stale >= 5:
                break
        model.load_state_dict(best_state)
        model.eval()

        def forecast(s):
            with torch.no_grad():
                result = model(torch.from_numpy(normalized[s:s + HISTORY][None]), 24)[0].numpy()
            return result * std + mean

        vp = np.concatenate([forecast(int(s)) for s in val_starts])
        vt = np.concatenate([raw[s + HISTORY:s + HISTORY + HORIZON] for s in val_starts])
        slope, intercept = [], []
        for c in range(len(CHANNELS)):
            x, y = vp[:, c].ravel(), vt[:, c].ravel()
            variance = np.var(x)
            m = float(np.mean((x - x.mean()) * (y - y.mean())) / variance) if variance > 1e-8 else 1.
            m = float(np.clip(m, .5, 1.5))
            slope.append(m)
            intercept.append(float(y.mean() - m * x.mean()))
        slope_arr, intercept_arr = np.array(slope)[None, :, None, None], np.array(intercept)[None, :, None, None]
        pred = np.concatenate([constrain(forecast(int(s)) * slope_arr + intercept_arr) for s in test_starts])
        truth = np.concatenate([raw[s + HISTORY:s + HISTORY + HORIZON] for s in test_starts])
        baseline = np.concatenate([np.repeat(raw[s + HISTORY - 1:s + HISTORY], 24, axis=0) for s in test_starts])
        report = {'model': metrics(pred, truth, climate), 'persistence': metrics(baseline, truth, climate),
                  'test_windows': len(test_starts), 'test_starts': test_starts.tolist(),
                  'training_windows': len(training_starts), 'validation_windows': len(val_starts),
                  'data_source': dataset['source'], 'evaluation': '固定测试窗口上的订正后确定性预报；窗口可能重叠',
                  'crps': None, 'crps_note': '本轮未做集合回报评估，不报告 CRPS；未导入 GFS，不报告 GFS 对比'}
        checkpoint = {'state_dict': best_state, 'mean': torch.from_numpy(mean), 'std': torch.from_numpy(std),
                      'slope': torch.tensor(slope), 'intercept': torch.tensor(intercept),
                      'dataset_id': dataset['id'], 'channels': CHANNELS, 'grid_shape': list(raw.shape[-2:]), 'horizon': 24}
        temporary = store.root / 'models' / (job_id + '.tmp')
        torch.save(checkpoint, temporary)
        temporary.replace(store.root / 'models' / (job_id + '.pt'))
        store.update(job_id, status='completed', progress=100, message='训练完成，已保存 24 小时权重及独立测试分区指标',
                     parameters=sum(p.numel() for p in model.parameters()), metrics=report,
                     elapsed_seconds=round(time.perf_counter() - started, 2), logs=logs)
    except Exception as exc:
        store.update(job_id, status='failed', message=str(exc))


def infer(checkpoint_path: Path, history, members):
    import torch
    from .model import MeteoFormer
    torch.set_num_threads(2)
    checkpoint = torch.load(checkpoint_path, map_location='cpu', weights_only=True)
    model = MeteoFormer()
    model.load_state_dict(checkpoint['state_dict'])
    model.eval()
    mean, std = checkpoint['mean'].numpy(), checkpoint['std'].numpy()
    slope = checkpoint['slope'].numpy()[None, :, None, None]
    intercept = checkpoint['intercept'].numpy()[None, :, None, None]
    normalized = (history - mean) / std
    rng = np.random.default_rng(42)
    outputs = []
    with torch.no_grad():
        for i in range(members):
            data = normalized if members == 1 else normalized + rng.normal(0, .02, normalized.shape).astype('float32')
            predicted = model(torch.from_numpy(data[None]), 24)[0].numpy() * std + mean
            outputs.append(constrain(predicted * slope + intercept))
    return np.stack(outputs)
