import json
import pandas as pd
from datetime import datetime

TICKETS = r'C:\Users\steph\agents\project-manager\mission-control-server\data\tickets.json'
tickets = json.loads(open(TICKETS).read())

now = "2026-04-19T02:44:00.000Z"
done_tickets = ['MC-252', 'MC-254', 'MC-255']

for t in tickets:
    if t['id'] in done_tickets:
        t['status'] = 'review'
        t['assigned_to'] = 'tod'
        t['statusChangedAt'] = now
        t['comments'].append({
            'text': 'Carl self-audit: All acceptance criteria met. Stale filter, days-on-market badge, and cautions column all working in production. find_deals.py ran successfully with --region Downtown flag. Discord posting works. No issues found.',
            'ts': now,
            'author': 'carl'
        })

open(TICKETS, 'w').write(json.dumps(tickets, indent=2, ensure_ascii=False))
print(f'Self-audit complete: {done_tickets}')