from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from app.config import settings


class InfluxDB:
    client: InfluxDBClient = None
    write_api = None
    query_api = None


influxdb = InfluxDB()


def connect_to_influx():
    influxdb.client = InfluxDBClient(
        url=settings.influxdb_url, token=settings.influxdb_token, org=settings.influxdb_org
    )
    influxdb.write_api = influxdb.client.write_api(write_options=SYNCHRONOUS)
    influxdb.query_api = influxdb.client.query_api()


def close_influx_connection():
    if influxdb.client:
        influxdb.client.close()


def write_sensor_point(point: Point):
    influxdb.write_api.write(bucket=settings.influxdb_bucket, org=settings.influxdb_org, record=point)
