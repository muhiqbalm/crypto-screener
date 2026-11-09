// PM2 config for the Strategy Lab worker. NOT started automatically.
//   pm2 start ecosystem.lab.config.js && pm2 save
// The worker runs under the screener venv; each job runs in a child process
// using the bmtm-v2 venv interpreter (LAB_ENGINE_PYTHON), niced and memory-capped.
module.exports = {
  apps: [
    {
      name: "bmtm-lab-worker",
      cwd: "/root/crypto-screener",
      script: "main_lab_worker.py",
      interpreter: "/root/crypto-screener/.venv/bin/python",
      autorestart: true,
      max_restarts: 20,
      restart_delay: 5000,
      kill_timeout: 15000,
      max_memory_restart: "300M",
      env: {
        PYTHONUNBUFFERED: "1",
        LAB_DB_PATH: "/root/crypto-screener/data/lab/lab.db",
        LAB_ENGINE_PATH: "/root/bmtm-lab-engine",
        LAB_ENGINE_PYTHON: "/root/bmtm-v2/venv/bin/python",
        LAB_DATA_DIR: "/root/crypto-screener/data/lab/cache/perp",
        LAB_ARTIFACTS_DIR: "/root/crypto-screener/data/lab/artifacts",
        LAB_MAX_CONCURRENT_JOBS: "1",
        LAB_JOB_NICE: "15",
        LAB_JOB_MEM_MB: "6144",
        LAB_JOB_TIMEOUT_S: "10800",
        LAB_OPTUNA_MAX_TRIALS: "60",
      },
    },
  ],
};
