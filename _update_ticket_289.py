import json

path = r'C:\Users\steph\agents\project-manager\mission-control-server\data\tickets.json'
with open(path, 'r', encoding='utf-8') as f:
    tickets = json.load(f)

ticket = next(t for t in tickets if t['id'] == 'MC-289')
ticket['status'] = 'review'
ticket['assigned_to'] = 'tod'
ticket['comments'].append({
    'text': 'MC-289 complete: health_monitor.py with get_source_stats/check_source_health/print_health_table, --check-health/--source CLI. run_pipeline.py tracks per-source errors+duration_secs, fires alert if total < 100. persist.py updated schema + live migration. 14/14 tests pass. Commit 6402fd2.',
    'ts': '2026-04-22T04:43:00.000Z',
    'author': 'carl'
})
ticket['statusChangedAt'] = '2026-04-22T04:43:00.000Z'

with open(path, 'w', encoding='utf-8') as f:
    json.dump(tickets, f, indent=2, ensure_ascii=False)

print('Done')