#!/usr/bin/env python3
"""Analyze route sizes in app.py"""

with open('src/app.py', 'r') as f:
    lines = f.readlines()

routes = []
current_route = None
start_line = 0

for i, line in enumerate(lines, 1):
    if '@app.route' in line:
        if current_route:
            routes.append((current_route, start_line, i-1, i-1-start_line))
        current_route = line.strip()
        start_line = i
    elif 'if __name__' in line and current_route:
        routes.append((current_route, start_line, i-1, i-1-start_line))
        break

print(f"Total routes: {len(routes)}")
print(f"\nLargest routes:")
routes.sort(key=lambda x: x[3], reverse=True)
for route, start, end, size in routes[:8]:
    print(f"{size:3d} lines (L{start:3d}-{end:3d}): {route[:60]}")

print(f"\nTotal API route lines: {sum(r[3] for r in routes)}")
print(f"Current file size: {len(lines)} lines")
print(f"Without API routes: ~{len(lines) - sum(r[3] for r in routes)} lines")
