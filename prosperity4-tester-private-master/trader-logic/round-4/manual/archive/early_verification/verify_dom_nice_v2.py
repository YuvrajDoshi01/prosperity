"""Verify DOM_NICE_v2 (DROP_60C + BUY 50 AC_35_P) on common 200M paths.
Also test 35_P BUY at various sizes to see if 50 is optimal."""
import numpy as np
import torch
import time

S0 = 50.0
SIGMA = 2.51
DT = 1.0 / (252 * 4)
N_3W = 60
N_2W = 40
CONTRACT_MULTIPLIER = 3000
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
DTYPE = torch.float32

QUOTES = {
    "AC":          (49.975, 50.025, 200),
    "AC_50_P":     (12.000, 12.050,  50),
    "AC_50_C":     (12.000, 12.050,  50),
    "AC_35_P":     ( 4.330,  4.350,  50),
    "AC_40_P":     ( 6.500,  6.550,  50),
    "AC_45_P":     ( 9.050,  9.100,  50),
    "AC_60_C":     ( 8.800,  8.850,  50),
    "AC_50_P_2":   ( 9.700,  9.750,  50),
    "AC_50_C_2":   ( 9.700,  9.750,  50),
    "AC_50_CO":    (22.200, 22.300,  50),
    "AC_40_BP":    ( 5.000,  5.100,  50),
    "AC_45_KO":    ( 0.150,  0.175, 500),
}
INSTR = list(QUOTES.keys())
N_INSTR = len(INSTR)


def gen_paths(n, gen):
    drift_step = -0.5 * SIGMA * SIGMA * DT
    vol_step = SIGMA * (DT ** 0.5)
    S = torch.full((n,), S0, dtype=DTYPE, device=DEVICE)
    min_S = S.clone()
    S_2w = None
    for k in range(N_3W):
        z = torch.randn(n, generator=gen, dtype=DTYPE, device=DEVICE)
        S = S * torch.exp(drift_step + vol_step * z)
        torch.minimum(min_S, S, out=min_S)
        if k+1 == N_2W:
            S_2w = S.clone()
    return S, S_2w, min_S


def compute_payoff_matrix(S_T, S_2w, min_S):
    n = S_T.shape[0]
    M = torch.zeros((N_INSTR, n), dtype=DTYPE, device=DEVICE)
    M[INSTR.index("AC")]         = S_T
    M[INSTR.index("AC_50_P")]    = torch.clamp(50 - S_T, min=0.0)
    M[INSTR.index("AC_50_C")]    = torch.clamp(S_T - 50, min=0.0)
    M[INSTR.index("AC_35_P")]    = torch.clamp(35 - S_T, min=0.0)
    M[INSTR.index("AC_40_P")]    = torch.clamp(40 - S_T, min=0.0)
    M[INSTR.index("AC_45_P")]    = torch.clamp(45 - S_T, min=0.0)
    M[INSTR.index("AC_60_C")]    = torch.clamp(S_T - 60, min=0.0)
    M[INSTR.index("AC_50_P_2")]  = torch.clamp(50 - S_2w, min=0.0)
    M[INSTR.index("AC_50_C_2")]  = torch.clamp(S_2w - 50, min=0.0)
    M[INSTR.index("AC_50_CO")] = torch.where(S_2w >= 50, torch.clamp(S_T - 50, min=0.0), torch.clamp(50 - S_T, min=0.0))
    M[INSTR.index("AC_40_BP")] = torch.where(S_T < 40, torch.full_like(S_T, 10.0), torch.zeros_like(S_T))
    M[INSTR.index("AC_45_KO")] = torch.where(min_S >= 35, torch.clamp(45 - S_T, min=0.0), torch.zeros_like(S_T))
    return M


# Define candidates: DROP_60C base + various 35_P add-ons
def make_pos(d):
    v = np.zeros(N_INSTR, dtype=np.int32)
    for k, q in d.items(): v[INSTR.index(k)] = q
    return v


CANDIDATES = {}
DROP_BASE = {"AC_50_CO": -50, "AC_45_KO": +500, "AC_40_BP": -50, "AC_50_P_2": +50, "AC_50_C_2": +50}
CANDIDATES["DROP_60C"] = make_pos(DROP_BASE)

# 35_P sweep (BUY only)
for q35 in [10, 25, 50]:
    d = dict(DROP_BASE); d["AC_35_P"] = +q35
    CANDIDATES[f"DROP+P35={q35}"] = make_pos(d)

# 40_P sweep
for q40 in [25, 50]:
    d = dict(DROP_BASE); d["AC_40_P"] = +q40
    CANDIDATES[f"DROP+P40={q40}"] = make_pos(d)

# Combo: 35_P + 40_P
for q35 in [25, 50]:
    for q40 in [25, 50]:
        d = dict(DROP_BASE); d["AC_35_P"] = +q35; d["AC_40_P"] = +q40
        CANDIDATES[f"DROP+P35={q35}+P40={q40}"] = make_pos(d)

# DOM_NICE_v2 — the proposed 6-position
CANDIDATES["DOM_NICE_v2"] = make_pos({**DROP_BASE, "AC_35_P": +50})

# DOM_NICE (prior recommendation)
CANDIDATES["DOM_NICE"] = make_pos({**DROP_BASE, "AC_45_P": +50, "AC_50_C": +30})

# DOM_NICE + 35_P (combined): DOM_NICE adds 45_P+50_C; v2 adds 35_P. What if both?
CANDIDATES["DOM_NICE+P35=25"] = make_pos({**DROP_BASE, "AC_45_P": +50, "AC_50_C": +30, "AC_35_P": +25})
CANDIDATES["DOM_NICE+P35=50"] = make_pos({**DROP_BASE, "AC_45_P": +50, "AC_50_C": +30, "AC_35_P": +50})

# DROP + 35_P (cleaner version) at full BUY
CANDIDATES["DROP+P35=50+P40=50"] = make_pos({**DROP_BASE, "AC_35_P": +50, "AC_40_P": +50})

# Run 200M paths shared
TOTAL = 200_000_000
CHUNK = 1_000_000
N_CHUNKS = TOTAL // CHUNK
SIMS_PER_TRIAL = 100
N_TRIALS = TOTAL // SIMS_PER_TRIAL
TRIALS_PER_CHUNK = CHUNK // SIMS_PER_TRIAL

names = list(CANDIDATES.keys())
positions = np.array([CANDIDATES[n] for n in names], dtype=np.int32)
n_strats = len(names)

pos_gpu = torch.tensor(positions, dtype=DTYPE, device=DEVICE)
bid_gpu = torch.tensor([QUOTES[s][0] for s in INSTR], dtype=DTYPE, device=DEVICE)
ask_gpu = torch.tensor([QUOTES[s][1] for s in INSTR], dtype=DTYPE, device=DEVICE)
cost_gpu = torch.clamp(pos_gpu, min=0.0) @ ask_gpu - torch.clamp(-pos_gpu, min=0.0) @ bid_gpu

trial_scores = np.empty((n_strats, N_TRIALS), dtype=np.float32)

print(f"Running {n_strats} strategies on {TOTAL:,} shared paths via GPU...")
t0 = time.time()
for ci in range(N_CHUNKS):
    gen = torch.Generator(device=DEVICE).manual_seed(20260427 + ci)  # different seed per chunk
    S_T, S_2w, min_S = gen_paths(CHUNK, gen)
    M = compute_payoff_matrix(S_T, S_2w, min_S)
    pnl = pos_gpu @ M - cost_gpu.unsqueeze(1)
    trial_chunk = pnl.view(n_strats, TRIALS_PER_CHUNK, SIMS_PER_TRIAL).mean(dim=2) * CONTRACT_MULTIPLIER
    tstart = ci * TRIALS_PER_CHUNK
    trial_scores[:, tstart:tstart+TRIALS_PER_CHUNK] = trial_chunk.cpu().numpy()
    del S_T, S_2w, min_S, M, pnl, trial_chunk
    torch.cuda.empty_cache()
    if (ci+1) % 50 == 0:
        elapsed = time.time() - t0
        print(f"  chunk {ci+1}/{N_CHUNKS} elapsed {elapsed:.1f}s")

print(f"\nDone in {time.time()-t0:.1f}s")
print(f"\n{'='*120}")
print(f"{n_strats} strategies x {TOTAL:,} paths = {N_TRIALS:,} trials each")
print(f"{'='*120}")
print(f"{'Strategy':<28} {'Mean':>13} {'Median':>13} {'SD':>13} {'Sharpe':>8} {'P>0':>6} {'CVaR-5%':>13} {'CVaR-2%':>13}")

stats = {}
for i, name in enumerate(names):
    s = trial_scores[i]
    mean = s.mean(); sd = s.std(ddof=1); med = np.median(s)
    pos_pct = (s > 0).mean() * 100
    sharpe = mean / sd if sd > 0 else 0
    sorted_s = np.sort(s)
    cvar5 = sorted_s[:N_TRIALS // 20].mean()
    cvar2 = sorted_s[:N_TRIALS // 50].mean()
    stats[name] = {"mean": mean, "sd": sd, "median": med, "pos": pos_pct, "sharpe": sharpe, "cvar5": cvar5, "cvar2": cvar2}

# Sort by mean
sorted_names = sorted(stats.keys(), key=lambda n: -stats[n]["mean"])
for name in sorted_names:
    s = stats[name]
    print(f"{name:<28} ${s['mean']:>+12,.0f} ${s['median']:>+12,.0f} ${s['sd']:>12,.0f} {s['sharpe']:>8.4f} {s['pos']:>5.1f}% ${s['cvar5']:>+12,.0f} ${s['cvar2']:>+12,.0f}")

# Paired diffs vs DROP_60C
print(f"\n{'='*120}")
print(f"PAIRED DIFFS vs DROP_60C (same paths, t-stats from 2M trials)")
print(f"{'='*120}")
drop_idx = names.index("DROP_60C")
drop_scores = trial_scores[drop_idx]

print(f"{'Strategy':<28} {'Mean d':>12} {'CVaR-5% d':>12} {'Sharpe d':>10} {'t-stat':>8}")
for i, name in enumerate(names):
    if name == "DROP_60C": continue
    diff = trial_scores[i] - drop_scores
    diff_mean = diff.mean()
    diff_se = diff.std(ddof=1) / np.sqrt(N_TRIALS)
    t_stat = diff_mean / diff_se if diff_se > 0 else 0
    cvar5_diff = stats[name]["cvar5"] - stats["DROP_60C"]["cvar5"]
    sharpe_diff = stats[name]["sharpe"] - stats["DROP_60C"]["sharpe"]
    print(f"{name:<28} ${diff_mean:>+11,.0f} ${cvar5_diff:>+11,.0f} {sharpe_diff:>+9.4f} {t_stat:>+8.2f}")
