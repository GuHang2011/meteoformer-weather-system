"""Command line entry for reproducible local workflows."""
import argparse
import json
import os
from pathlib import Path

import xarray as xr

from .data import demo_dataset, prepare, save_grid, summary
from .forecast import run_forecast
from .store import Store
from .training import train, validate_model_dataset


def main():
    parser = argparse.ArgumentParser(description='MeteoFormer local data / training / inference')
    parser.add_argument('--data-dir', default=os.getenv('METEO_DATA_DIR', str(Path(__file__).resolve().parents[1] / 'data')))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('demo')
    upload = sub.add_parser('import')
    upload.add_argument('file', type=Path)
    upload.add_argument('--source', choices=['ERA5', 'GFS', 'other'], default='other')
    upload.add_argument('--grid-size', type=int, choices=[16, 32, 64], default=16)
    upload.add_argument('--hourly-precipitation', action='store_true', required=True)
    training = sub.add_parser('train')
    training.add_argument('dataset_id')
    training.add_argument('--epochs', type=int, default=3, choices=range(3, 61))
    training.add_argument('--samples', type=int, default=16, choices=range(2, 129))
    prediction = sub.add_parser('predict')
    prediction.add_argument('dataset_id')
    prediction.add_argument('--model-id')
    prediction.add_argument('--members', type=int, default=1, choices=range(1, 9))
    args = parser.parse_args()
    store = Store(Path(args.data_dir))
    if args.command in ('demo', 'import'):
        from uuid import uuid4
        raw = demo_dataset() if args.command == 'demo' else xr.open_dataset(args.file)
        with raw:
            cleaned, notes = prepare(raw, getattr(args, 'grid_size', None))
            key = uuid4().hex
            save_grid(cleaned, store.root / 'datasets' / (key + '.zarr'))
            result = store.add('dataset', {'name': '合成演示数据' if args.command == 'demo' else args.file.name,
                              'source': 'synthetic' if args.command == 'demo' else args.source,
                              **summary(cleaned, notes)}, key=key)
    elif args.command == 'train':
        dataset = store.get(args.dataset_id, 'dataset')
        job = store.add('job', {'dataset_id': dataset['id'], 'dataset_name': dataset['name'], 'source': dataset['source'],
                    'status': 'queued', 'epochs': args.epochs, 'samples': args.samples, 'epoch': 0,
                    'progress': 0, 'logs': [], 'message': '等待训练启动'})
        train(store, job['id'], dataset, args.epochs, args.samples)
        result = store.get(job['id'])
        if result['status'] != 'completed':
            raise SystemExit(result['message'])
    else:
        dataset = store.get(args.dataset_id, 'dataset')
        if args.model_id:
            job = store.get(args.model_id, 'job')
            if job['status'] != 'completed':
                raise SystemExit('模型必须已完成训练')
            validate_model_dataset(store, job, dataset)
        elif args.members != 1:
            raise SystemExit('集合预报需要模型权重')
        result = run_forecast(store, dataset, 'meteoformer' if args.model_id else 'persistence', args.members, args.model_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
