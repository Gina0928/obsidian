"""Shared database configuration for slow SQL analysis tools."""

DB_HOST = "rn-bp1151j106lak7k01-clusterq85-l1.mysql.rds.aliyuncs.com"
DB_PORT = 3306
DB_USER = "slow_sql_user"
DB_PASSWORD = "Bn&KITDHz6"
DB_NAME = "jy_monitor"  # slow_sql_log / slow_sql_live_log / slow_db_monitor_log 所在的数据库

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
