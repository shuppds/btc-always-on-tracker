import json, os, urllib.request, datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'tracker.json'
API = 'https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=5'

def fetch():
    req = urllib.request.Request(API, headers={'User-Agent':'BTC-Always-On-Tracker/1.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        rows = json.loads(r.read().decode())
    return [{'open_time': int(x[0]), 'open': float(x[1]), 'high': float(x[2]), 'low': float(x[3]), 'close': float(x[4]), 'close_time': int(x[6])} for x in rows]

def load():
    if DATA.exists():
        try: return json.loads(DATA.read_text())
        except Exception: pass
    return {'updated_at': None, 'source': 'Binance BTCUSDT spot 15m candles', 'early': [], 'post_lock': [], 'last_seen_closed': 0, 'notes': 'Scheduled cloud tracker. Signals are heuristic, not calibrated probabilities.'}

def score(candles):
    # Transparent simple momentum heuristic from recent closed candles; this is not the local dashboard's full order-flow model.
    closes = [c['close'] for c in candles]
    if len(closes) < 4: return 'WAIT', 0
    short = closes[-1] - closes[-3]
    long = closes[-1] - closes[0]
    delta = (short / closes[-3] + long / closes[0]) * 100
    if delta > 0.035: return 'UP', min(89, int(70 + min(19, abs(delta)*80)))
    if delta < -0.035: return 'DOWN', min(89, int(70 + min(19, abs(delta)*80)))
    return 'WAIT', int(50 + min(19, abs(delta)*100))

def main():
    state = load(); candles = fetch(); now = int(time.time()*1000)
    # Binance returns the currently forming candle last. Closed candles have close_time < now.
    closed = [c for c in candles if c['close_time'] < now]
    if not closed: raise RuntimeError('No closed 15-minute BTC candle returned')
    current = candles[-1]
    round_start = current['open_time']
    elapsed = max(0, now-round_start)
    signal, confidence = score(closed[-4:])
    # Log at most one call per round per phase; phase classification is based on the candle's elapsed time.
    if signal in ('UP','DOWN') and confidence > 70:
        phase = 'early' if elapsed < 180000 else 'post_lock'
        hist = state[phase]
        if not any(x.get('round_start') == round_start for x in hist):
            hist.append({'round_start': round_start, 'call_time': now, 'phase': phase, 'signal': signal, 'score': confidence, 'open_price': current['open'], 'status': 'PENDING'})
    # Resolve calls against the close of the exact 15m candle they belong to.
    for phase in ('early','post_lock'):
        for item in state[phase]:
            if item.get('status') != 'PENDING': continue
            match = next((c for c in closed if c['open_time'] == item['round_start']), None)
            if match:
                diff = match['close'] - match['open']
                item['final_price'] = match['close']
                item['status'] = 'FLAT' if abs(diff) < 1e-8 else ('HIT' if (item['signal']=='UP' and diff>0) or (item['signal']=='DOWN' and diff<0) else 'MISS')
                item['resolved_at'] = now
    # Keep latest 300 records in each list.
    state['early'] = state['early'][-300:]; state['post_lock'] = state['post_lock'][-300:]
    state['updated_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    state['current_round'] = {'round_start': round_start, 'open_price': current['open'], 'elapsed_ms': elapsed, 'current_price': closed[-1]['close'], 'latest_signal': signal, 'score': confidence}
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(state, indent=2))
    print('Updated tracker:', state['updated_at'], 'round', round_start, 'signal', signal, confidence)

if __name__ == '__main__': main()
