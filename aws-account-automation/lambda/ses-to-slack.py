# Lambda to send SES Emails Messages to Slack
from base64 import b64decode
from botocore.exceptions import ClientError
import boto3
import email
import json
import os
import urllib3

import logging
logger = logging.getLogger()
logger.setLevel(getattr(logging, os.getenv('LOG_LEVEL', default='INFO')))
logging.getLogger('botocore').setLevel(logging.WARNING)
logging.getLogger('boto3').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)


def get_webhook(secret_name):
  client = boto3.client('secretsmanager')
  try:
    get_secret_value_response = client.get_secret_value(SecretId=secret_name)
  except ClientError as e:
    logger.critical(f"Unable to get secret value for {secret_name}: {e}")
    return(None)
  else:
    if 'SecretString' in get_secret_value_response:
      secret_value = get_secret_value_response['SecretString']
    else:
      secret_value = get_secret_value_response['SecretBinary']
  try:
    secret_dict = json.loads(secret_value)
    return(secret_dict['webhook_url'])
  except Exception as e:
    logger.critical(f"Error during Credential and Service extraction: {e}")
    raise

WEBHOOK=get_webhook(os.environ['WEBHOOK'])
http = urllib3.PoolManager()

def lambda_handler(event, context):
  logger.info("Received event: " + json.dumps(event, sort_keys=True))
  for record in event['Records']:
    process_message(record['ses'])
# end handler


def process_message(message):
  logger.debug("processing message: " + json.dumps(message, sort_keys=True))
  message_id = message['mail']['messageId']

  raw_message = fetch_from_s3(message_id)
  if raw_message is None:
    message_body = "Unable to get Message"
  else:
    message_body = parse_email_file(raw_message).decode('utf-8')

  logger.debug(f"Found Message body: {message_body}")

  slack_message = {
    'channel': os.environ['SLACK_CHANNEL'],
    'icon_emoji': os.environ['ICON_EMOJI'],
    'attachments': [
      {
        'footer': message_id,
        'pretext': f"New Email for {os.environ['DOMAIN']}",
        'color': "red",
        'title': f"Subject: {message['mail']['commonHeaders']['subject']}",
        'fields': [
                {"title": "From:","value": message['mail']['commonHeaders']['from'][0], "short": True},
                {"title": "To:","value": str(message['mail']['commonHeaders']['to']), "short": True},
                {"title": "Date:","value": message['mail']['commonHeaders']['date'], "short": True},
                {"title": "Body:","value": message_body,"short": False},
        ],
        # "text": "Message body goes here",
        'mrkdwn_in': ["title"],
      }
    ]
  }
  try:
    r = http.request('POST', WEBHOOK, body=json.dumps(slack_message))
    logger.info(f"Message posted to {os.environ['SLACK_CHANNEL']}")
  except Exception as e:
    logger.error(f"Request failed: {e}")
# End process_message()


def parse_email_file(raw_message):
  b = email.message_from_string(raw_message)
  body = ""

  if b.is_multipart():
    for part in b.walk():
      ctype = part.get_content_type()
      cdispo = str(part.get('Content-Disposition'))

      # skip any text/plain (txt) attachments
      if ctype == 'text/plain' and 'attachment' not in cdispo:
        body = part.get_payload(decode=True)  # decode
        break
  # not multipart - i.e. plain text, no attachments, keeping fingers crossed
  else:
    body = b.get_payload(decode=True)
  return(body)


def fetch_from_s3(message_id):
  s3_client = boto3.client('s3')
  try:
    object_key = f"{os.environ['DOMAIN']}/{message_id}"
    response = s3_client.get_object(Bucket=os.environ['BUCKET'], Key=object_key)
    return (response['Body'].read().decode('utf-8'))
  except Exception as e:
    logger.error(f"Unable to get Object s3://{os.environ['BUCKET']}/{object_key}: {e}")
    return(None)

# End of Function