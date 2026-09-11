import numpy as np


lower = 670
higher = 920

import matplotlib.pyplot as plt
from matplotlib.widgets import Slider

import os

npz_file = 'analysis/avg_data.npz'

if os.path.exists(npz_file):
    print(f"Loading data from {npz_file}...")
    data = np.load(npz_file)
    valid_L = data['L']
    valid_H = data['H']
    avg_h_bids = data['A']
    all_pnls = data['PnL']
else:
    print("Vectorizing computation...")
    l_bids = np.arange(lower, higher)
    h_bids = np.arange(lower, higher)
    counterparties = np.arange(lower, higher + 5, 5)
    avg_h_bids = np.arange(lower - 0.001, higher, 1)

    L, H, C = np.meshgrid(l_bids, h_bids, counterparties, indexing='ij')

    # Only consider combinations where higher_bid > lower_bid
    valid_mask = H[:, :, 0] > L[:, :, 0]
    valid_L = L[:, :, 0][valid_mask]
    valid_H = H[:, :, 0][valid_mask]

    # Precompute conditions that do not depend on A
    cond1 = L > C
    pnl1_sum = np.sum(np.where(cond1, 920 - L, 0), axis=-1)
    cond2_base = (~cond1) & (H > C)

    all_pnls = np.zeros((len(avg_h_bids), len(valid_L)))

    for i, A in enumerate(avg_h_bids):
        A = float(A)
        # Cond2 logic
        cond2 = cond2_base & (H > A)
        pnl2 = np.where(cond2, 920 - H, 0)
        
        # Cond3 logic
        cond3 = cond2_base & (H <= A)
        val3 = (920 - H) * ((920 - A) / (920 - H))**3
        pnl3 = np.where(cond3, val3, 0)
        
        total_pnl = pnl1_sum + np.sum(pnl2 + pnl3, axis=-1)
        all_pnls[i] = total_pnl[valid_mask]

    print("Done computing!")
    np.savez_compressed(npz_file, L=valid_L, H=valid_H, A=avg_h_bids, PnL=all_pnls)
    print("Saved to npz.")

print("Normalizing PnLs...")
mean_pnl = np.mean(all_pnls)
if mean_pnl != 0:
    pass #all_pnls = all_pnls / mean_pnl

avg_bids = np.round(avg_h_bids, 3)

if len(avg_bids) == 0:
    print("No data computed!")
    exit()

fig = plt.figure(figsize=(12, 8))
ax = fig.add_subplot(111, projection='3d')
plt.subplots_adjust(bottom=0.25)

init_idx = len(avg_bids) // 2
init_avg = avg_bids[init_idx]

ax_slider = plt.axes([0.2, 0.1, 0.65, 0.03])
slider = Slider(
    ax=ax_slider, 
    label='Avg Higher Bid', 
    valmin=min(avg_bids), 
    valmax=max(avg_bids), 
    valinit=init_avg, 
    valstep=avg_bids
)

def plot_data(idx):
    ax.clear()
    avg_val = avg_bids[idx]
    
    x = valid_L
    y = valid_H
    z = all_pnls[idx]
    
    ax.set_xlabel('Lower Bid')
    ax.set_ylabel('Higher Bid')
    ax.set_zlabel('PnL')
    ax.set_title(f'PnL for Avg Higher Bid: {avg_val:.3f}')
    
    # Plot scatter
    sc = ax.scatter(x, y, z, c=z, cmap='viridis', alpha=0.6)
    
    # Highlight max PnL
    max_idx = np.argmax(z)
    ax.plot([x[max_idx]], [y[max_idx]], [z[max_idx]], 'ro', markersize=10, 
            label=f'Max PnL: {z[max_idx]:.2f}\nat ({x[max_idx]}, {y[max_idx]})')
    ax.legend()
    fig.canvas.draw_idle()

def update(val):
    avg_val = slider.val
    idx = np.abs(avg_bids - avg_val).argmin()
    plot_data(idx)

slider.on_changed(update)
plot_data(init_idx)

plt.show()