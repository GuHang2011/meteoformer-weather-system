"""Compact Swin + ConvLSTM research model; no pretrained skill is implied."""
import torch
from torch import nn
from torch.nn import functional as F


class WindowBlock(nn.Module):
    def __init__(self, dim, window=4, shift=0):
        super().__init__()
        self.window, self.shift = window, shift
        self.norm = nn.LayerNorm(dim)
        self.attention = nn.MultiheadAttention(dim, 4, batch_first=True)
        self.norm2 = nn.LayerNorm(dim)
        self.mlp = nn.Sequential(nn.Linear(dim, dim * 2), nn.GELU(), nn.Linear(dim * 2, dim))
        self.relative_bias = nn.Parameter(torch.zeros((2 * window - 1) ** 2, 4))
        coords = torch.stack(torch.meshgrid(torch.arange(window), torch.arange(window), indexing='ij')).flatten(1)
        relative = coords[:, :, None] - coords[:, None, :]
        relative += window - 1
        self.register_buffer('relative_index', relative[0] * (2 * window - 1) + relative[1])

    def partition(self, x):
        b, h, w, c = x.shape
        s = self.window
        return x.reshape(b, h // s, s, w // s, s, c).permute(0, 1, 3, 2, 4, 5).reshape(-1, s*s, c)

    def forward(self, field):
        x = field.permute(0, 2, 3, 1)
        b, h, w, c = x.shape
        s = self.window
        if h % s or w % s:
            raise ValueError('编码后网格必须能被窗口大小整除')
        if self.shift:
            x = torch.roll(x, (-self.shift, -self.shift), dims=(1, 2))
        windows = self.partition(x)
        bias = self.relative_bias[self.relative_index].permute(2, 0, 1)
        mask = bias.unsqueeze(0).expand(windows.shape[0], -1, -1, -1)
        if self.shift:
            regions = x.new_zeros((1, h, w, 1))
            sections = (slice(0, -s), slice(-s, -self.shift), slice(-self.shift, None))
            for i, ys in enumerate(sections):
                for j, xs in enumerate(sections):
                    regions[:, ys, xs] = i * 3 + j
            rw = self.partition(regions).squeeze(-1)
            blocked = (rw[:, :, None] != rw[:, None, :]).repeat(b, 1, 1)
            mask = mask + blocked[:, None].to(x.dtype) * -100.
        z = self.norm(windows)
        z = windows + self.attention(z, z, z, attn_mask=mask.reshape(-1, s*s, s*s), need_weights=False)[0]
        z = z + self.mlp(self.norm2(z))
        z = z.reshape(b, h // s, w // s, s, s, c).permute(0, 1, 3, 2, 4, 5).reshape(b, h, w, c)
        if self.shift:
            z = torch.roll(z, (self.shift, self.shift), dims=(1, 2))
        return z.permute(0, 3, 1, 2)


class ConvLSTMCell(nn.Module):
    def __init__(self, channels, hidden):
        super().__init__()
        self.hidden = hidden
        self.gates = nn.Conv2d(channels + hidden, 4 * hidden, 3, padding=1)

    def forward(self, x, state=None):
        if state is None:
            h = x.new_zeros(x.shape[0], self.hidden, *x.shape[-2:])
            c = torch.zeros_like(h)
        else:
            h, c = state
        i, f, o, g = self.gates(torch.cat([x, h], dim=1)).chunk(4, dim=1)
        c = f.sigmoid() * c + i.sigmoid() * g.tanh()
        return o.sigmoid() * c.tanh(), c


class MeteoFormer(nn.Module):
    def __init__(self, channels=6, dim=16):
        super().__init__()
        self.encoder = nn.Sequential(nn.Conv2d(channels, dim, 2, stride=2),
                                     WindowBlock(dim), WindowBlock(dim, shift=2),
                                     nn.Conv2d(dim, dim * 2, 2, stride=2), nn.GELU())
        self.memory = ConvLSTMCell(dim * 2, dim * 2)
        self.decoder = nn.Sequential(nn.ConvTranspose2d(dim * 2, dim, 4, 2, 1), nn.GELU(),
                                     nn.ConvTranspose2d(dim, channels, 4, 2, 1))

    def forward(self, history, steps=24):
        state = None
        for frame in history.unbind(dim=1):
            state = self.memory(self.encoder(frame), state)
        last, outputs = history[:, -1], []
        for i in range(steps):
            last = last + .1 * self.decoder(state[0])
            outputs.append(last)
            if i + 1 < steps:
                state = self.memory(self.encoder(last), state)
        return torch.stack(outputs, dim=1)


def weather_loss(pred, target):
    mse = F.mse_loss(pred, target)
    grad = F.l1_loss(torch.diff(pred, dim=-1), torch.diff(target, dim=-1))
    grad += F.l1_loss(torch.diff(pred, dim=-2), torch.diff(target, dim=-2))
    rain = F.smooth_l1_loss(pred[:, :, 4], target[:, :, 4])
    spectral = (torch.fft.rfft2(pred, norm='ortho') - torch.fft.rfft2(target, norm='ortho')).abs().mean()
    return mse + .1 * grad + .5 * rain + .05 * spectral
