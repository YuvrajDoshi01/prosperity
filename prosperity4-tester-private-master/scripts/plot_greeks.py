import pandas as pd
import matplotlib.pyplot as plt
import os
import argparse

def main():
    parser = argparse.ArgumentParser(description="Plot Greeks Dashboard")
    parser.add_argument('--day', type=int, default=0, help='Day to plot (0, 1, or 2)')
    parser.add_argument('--save', action='store_true', help='Save the plot to a file instead of showing it')
    parser.add_argument('--show-all', action='store_true', help='Include deep ITM options (VEV_4000, VEV_4500) which can distort the graphs due to IV jumping')
    args = parser.parse_args()

    filepath = f"data/round3_greeks/greeks_round_3_day_{args.day}.csv"
    if not os.path.exists(filepath):
        print(f"File {filepath} not found.")
        return

    print(f"Loading data for Day {args.day}...")
    df = pd.read_csv(filepath, sep=';')
    
    # Greeks to plot
    greeks = ['IV', 'Delta', 'Gamma', 'Vega', 'Theta', 'Rho']
    
    # Create subplots: 2 rows, 3 columns
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle(f"Options Greeks Dashboard - Day {args.day}", fontsize=18, fontweight='bold')
    
    axes = axes.flatten()
    
    # Get all products, optionally sort them by Strike Price if available
    products = sorted(df['product'].unique())
    
    # Filter out deep ITM options by default to prevent graph distortion
    if not args.show_all:
        products = [p for p in products if p not in ['VEV_4000', 'VEV_4500']]
    
    # Iterate over each greek and plot
    for i, greek in enumerate(greeks):
        ax = axes[i]
        for prod in products:
            prod_df = df[df['product'] == prod]
            ax.plot(prod_df['timestamp'], prod_df[greek], label=prod, alpha=0.8, linewidth=1.5)
            
        ax.set_title(greek, fontsize=14)
        ax.set_xlabel("Timestamp", fontsize=10)
        ax.set_ylabel("Value", fontsize=10)
        ax.grid(True, linestyle='--', alpha=0.5)
        
        # Add legend to the first plot
        if i == 0:
            ax.legend(loc='best', fontsize='small', ncol=2)
            
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    
    if args.save:
        out_file = f"data/round3_greeks/dashboard_day_{args.day}.png"
        plt.savefig(out_file, dpi=300)
        print(f"Saved dashboard to {out_file}")
    else:
        plt.show()

if __name__ == '__main__':
    main()
