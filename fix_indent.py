#!/usr/bin/env python3
"""Fix indentation in app.py main block"""

with open('src/app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(len(lines)):
    if lines[i].strip() == "if __name__ == '__main__':":
        # Check if next line needs fixing
        if i+1 < len(lines) and not lines[i+1].startswith('    '):
            lines[i+1] = '    from .initialization import startup_checks\n'
            lines[i+2] = '    startup_checks()\n'
            lines[i+3] = '    \n'
            lines[i+4] = '    HOST = os.environ.get("SERVER_HOST", "localhost")\n'
            lines[i+5] = '    try:\n'
            lines[i+6] = '        PORT = int(os.environ.get("SERVER_PORT", "5000"))\n'
            lines[i+7] = '    except ValueError:\n'
            lines[i+8] = '        PORT = 5000\n'
            lines[i+9] = '    \n'
            lines[i+10] = '    logger.info(f"Starting Flask server on {HOST}:{PORT}")\n'
            lines[i+11] = '    app.run(HOST, PORT, debug=True, use_reloader=False)\n'
        break

with open('src/app.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('Indentation fixed')
