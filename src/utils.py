import pathway as pw
import requests

def send_discord_alerts(
    message: pw.ColumnReference, discord_webhook_url: str
):
    def send_discord_alert(key, row, time, is_addition):
        if not is_addition:
            return
        alert_message = row[message.name]

        payload = {'content': alert_message}
        requests.post(
            discord_webhook_url,
            json=payload
        ).raise_for_status()

    pw.io.subscribe(message._table, send_discord_alert)