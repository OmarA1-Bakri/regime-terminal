module.exports = {
  apps: [{
    name: "tao-monitor",
    script: require("os").homedir() + "/Desktop/TAO_WALLET/tao_monitor.py",
    interpreter: "python3",
    cron_restart: "0 * * * *",
    autorestart: false,
    watch: false,
    out_file: require("os").homedir() + "/Desktop/TAO_WALLET/tao_monitor.log",
    error_file: require("os").homedir() + "/Desktop/TAO_WALLET/tao_monitor_err.log",
  }],
};
