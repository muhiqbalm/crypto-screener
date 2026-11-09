"""Strategy Lab worker entry point (PM2 process ``bmtm-lab-worker``).

Runs separately from bmtm-api so research jobs can never block or crash the
live webhook. Usage: python main_lab_worker.py
"""
from src.lab.worker import main

if __name__ == "__main__":
    main()
