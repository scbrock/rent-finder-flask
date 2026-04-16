#!/usr/bin/env python3
"""
Railway deployment helper for rent_finder.
Run this from the rent_finder/ directory.

Prerequisites:
1. Install Railway CLI: npm install -g @railway/cli
2. Login: railway login
3. Then run: python deploy.py

The .env file already has:
  RAILWAY_API_TOKEN=7f9aa1d4-1850-4822-a0eb-9448939815da
  ORS_API_KEY=<key>
  SENDGRID_API_KEY=<key>
"""

import subprocess
import os

RAILWAY_TOKEN = os.environ.get('RAILWAY_API_TOKEN', '7f9aa1d4-1850-4822-a0eb-9448939815da')

def deploy():
    # Set token
    os.environ['RAILWAY_TOKEN'] = RAILWAY_TOKEN
    
    # Run railway up
    result = subprocess.run(
        ['railway', 'up', '--service', 'rent-finder', '--variable', 'PYTHONBLABLA=1'],
        capture_output=True, text=True
    )
    print(result.stdout)
    print(result.stderr)
    return result.returncode == 0

if __name__ == '__main__':
    deploy()