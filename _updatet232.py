import json
from datetime import datetime, timezone

ts = json.load(open(r'C:\Users\steph\agents\project-manager\mission-control-server\data\tickets.json'))
t = next(x for x in ts if x['id'] == 'MC-232')
t['status'] = 'review'
t['assigned_to'] = 'tod'
t['statusChangedAt'] = t.get('statusChangedAt') or datetime.now(timezone.utc).isoformat()
t.setdefault('comments', []).append({
    'text': 'MC-232 complete: read_state() and write_state() now handle encoding errors gracefully (try utf-8 first, fallback to iso-8859-1).',
    'ts': datetime.now(timezone.utc).isoformat(),
    'author': 'carl'
})
json.dump(ts, open(r'C:\Users\steph\agents\project-manager\mission-control-server\data\tickets.json', 'w'), indent=2, ensure_ascii=False)
print('done')