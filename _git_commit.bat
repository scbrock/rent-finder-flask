@echo off
git -C C:\Users\steph\.openclaw\workspace-coding\rent_finder add RENT_PROGRESS.md
git -C C:\Users\steph\.openclaw\workspace-coding\rent_finder commit -m "MC-287: Update RENT_PROGRESS.md with cold boot fix findings [Carl]"
git -C C:\Users\steph\.openclaw\workspace-coding\rent_finder push
git -C C:\Users\steph\.openclaw\workspace-coding\rent_finder add _cleanup.bat
git -C C:\Users\steph\.openclaw\workspace-coding\rent_finder rm --cached _cleanup.bat
git -C C:\Users\steph\.openclaw\workspace-coding\rent_finder commit -m "cleanup temp files"
git -C C:\Users\steph\.openclaw\workspace-coding\rent_finder push
