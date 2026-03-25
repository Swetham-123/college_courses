#!/usr/bin/env python3
"""
Monitor scraper progress and notify when complete
"""
import os
import time
from pathlib import Path
from datetime import datetime
import subprocess

OUTPUT_DIR = Path("output")
TARGET_COUNT = 700
CHECK_INTERVAL = 10  # seconds between checks

def get_scraped_count():
    """Count JSON files in output directory"""
    return len(list(OUTPUT_DIR.glob("*.json")))

def send_notification(title, message):
    """Send Windows notification"""
    try:
        # Use PowerShell for Windows notification
        cmd = f'''
        Add-Type –AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            '{message}',
            '{title}',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information
        )
        '''
        subprocess.run(["powershell", "-Command", cmd], capture_output=True)
    except Exception as e:
        print(f"Notification failed: {e}")

def main():
    print("=" * 70)
    print("SCRAPER PROGRESS MONITOR")
    print("=" * 70)
    print(f"Target: {TARGET_COUNT} universities")
    print(f"Check interval: {CHECK_INTERVAL} seconds")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()
    
    start_time = time.time()
    last_count = 0
    
    while True:
        try:
            current_count = get_scraped_count()
            elapsed_seconds = time.time() - start_time
            elapsed_minutes = elapsed_seconds / 60
            
            if current_count != last_count:
                rate = current_count / elapsed_seconds if elapsed_seconds > 0 else 0
                remaining = TARGET_COUNT - current_count
                eta_seconds = remaining / rate if rate > 0 else 0
                eta_minutes = eta_seconds / 60
                
                percentage = (current_count / TARGET_COUNT) * 100
                
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"Progress: {current_count}/{TARGET_COUNT} ({percentage:.1f}%) | "
                      f"Rate: {rate:.2f}/sec | "
                      f"Elapsed: {elapsed_minutes:.1f}min | "
                      f"ETA: {eta_minutes:.1f}min")
                
                last_count = current_count
            
            # Check if complete
            if current_count >= TARGET_COUNT:
                elapsed_minutes = (time.time() - start_time) / 60
                print()
                print("=" * 70)
                print("✅ SCRAPING COMPLETED!")
                print("=" * 70)
                print(f"Total universities scraped: {current_count}/{TARGET_COUNT}")
                print(f"Time taken: {elapsed_minutes:.1f} minutes")
                print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print()
                print("📁 Output location: output/")
                print("📊 Summary: output/_summary.json")
                print("=" * 70)
                
                # Send notification
                send_notification(
                    "Scraper Completed! ✅",
                    f"All {current_count} universities scraped successfully!\n"
                    f"Time: {elapsed_minutes:.1f} minutes\n"
                    f"Output: {OUTPUT_DIR.absolute()}"
                )
                
                break
            
            time.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            print("\n⏹ Monitoring stopped by user")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
