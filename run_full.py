import os, sys, warnings
warnings.filterwarnings('ignore')
os.chdir(r'C:\Users\steph\.openclaw\workspace-coding\rent_finder')
sys.argv = ['find_deals.py']  # no args = all regions, fresh run

import find_deals
find_deals.main()