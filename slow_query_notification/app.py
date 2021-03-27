# template.yaml で以下の環境変数を設定してください
# TZ: タイムゾーン('Asia/Tokyo' など)
# CLOUDWATCH_REGION: 通知したいログが存在するリージョン('ap-northeast-1' など)
# SLACK_API_TOKEN
# SLACK_CHANNEL_ID
# POSTPONEMENT_BEFORE_LOG_EXTRACTION: ログ取得に失敗した時の再取得までの待機時間（秒）
# MAX_RETRY_COUNT_GET_LOG: ログ再取得実行の上限回数
# PERIOD_LOG_EXTRACTION: ログ取得時間の幅（秒）
# NOTIFICATION_COLOR_STANDARD: Slack通知色を決めるクエリ実行時間の基準値（秒）

import json, os, zlib, base64, datetime, boto3, calendar, sqlparse, re, pytz, requests, copy, time, urllib

ENVIRONMENT_VARIABLE_SET = [
	'TZ',
	'CLOUDWATCH_REGION',
	'SLACK_API_TOKEN',
	'SLACK_CHANNEL_ID',
	'POSTPONEMENT_BEFORE_LOG_EXTRACTION',
	'MAX_RETRY_COUNT_GET_LOG',
	'PERIOD_LOG_EXTRACTION',
	'NOTIFICATION_COLOR_STANDARD'
]

pattern_datetime = re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')


# 実行されるlambda関数
def lambda_handler(event, context):
	# 必要な環境変数がセットされているかを確認
	if check_environment_variables(ENVIRONMENT_VARIABLE_SET):
		raise Exception

	# CloudWatchLogsのイベントデータからslow queryの発生時刻を取得
	event_data_zip = zlib.decompress(base64.b64decode(event['awslogs']['data']), 16+zlib.MAX_WBITS)
	event_data_json = json.loads(event_data_zip)
	if event_data_json['logGroup'] is None or event_data_json['logGroup'] == '':
		return 'Failed to process {} record. event_data_json[\'logGroup\'] is None'.format(len(event['awslogs']))
	executed_at_str = pattern_datetime.search(event_data_json['logEvents'][0]['message']).group()

	# ログストリームの抽出対象時刻をUNIXタイムに変換（遅延の発生時刻 ± PERIOD_LOG_EXTRACTION 秒）
	start_time_log_extraction, end_time_log_extraction = make_period_log_extraction(executed_at_str)

	# ログストリームからログデータを取得
	# ログが取得できる状態にない場合があるため時間を空けて複数回試行する
	retry_count = 0
	while True:
		log_data = boto3.client('logs').get_log_events(
			logGroupName = event_data_json['logGroup'],
			logStreamName = event_data_json['logStream'],
			startTime = start_time_log_extraction,
			endTime = end_time_log_extraction
		)
		if len(log_data['events']) != 0:
			break

		retry_count+= 1
		if retry_count >= int(os.environ.get('MAX_RETRY_COUNT_GET_LOG')):
			print('Failed to get log data.')
			return

		print('No log data in Cloud Watch Logs. Retry to get log.')
		time.sleep(int(os.environ.get('POSTPONEMENT_BEFORE_LOG_EXTRACTION')))

	query_logs = list(filter(lambda log: 'Query Text' in log['message'], log_data['events']))
	param_logs = list(filter(lambda log: 'parameters' in log['message'], log_data['events']))

	# ログを整形
	parsed_msgs = []
	for log in query_logs:
		# クエリログを、実行時刻・IP・処理時間・クエリタイプ・実行クエリ・実行計画・処理コストにパース
		query_msg, identify_info = parse_query_log(log['message'])

		# 対応するパラメータログを取得し、クエリログの実行クエリ部をパラメータ置換
		matched_param_log = list(filter(lambda log: identify_info in log['message'], param_logs))
		if len(matched_param_log) != 0:
			query_msg['query'] = parse_parameters_log(matched_param_log[0]['message'], query_msg['query'])

		parsed_msgs.append(query_msg)

	# Slackに通知する
	for msg in parsed_msgs:
		# 本文に簡単なサマリ
		msg_params = {
			'username': 'Slow Query Notification',
			'icon_emoji': make_slack_icon(msg['query_type']),
			'attachments': {
				'color' : make_slack_color(msg['duration']),
				'mrkdwn_in': ['text', 'pretext'],
				'fields' : [
					{
						'value' : '%s: %.2f s  (cost: %s)' % (msg['query_type'], msg['duration'], msg['explain_cost'])
					}
				]
			}
		}
		response = send_message_to_slack(msg_params)

		# スレッドに詳細
		msg_params['attachments']['fields'] = [
			{
				'title' : 'Query Type',
				'value' : msg['query_type'],
				'short' : 'true'
			}, {
				'title' : 'Actual Duration',
				'value' : '%.2f s  (cost: %s)' % (msg['duration'], msg['explain_cost']),
				'short' : 'true'
			}, {
				'title' : 'Executed At',
				'value' : msg['executed_at'],
				'short' : 'true'
			}, {
				'title' : 'IP',
				'value' : msg['client_ip'],
				'short' : 'true'
			}, {
				'title' : 'Query Text',
				'value' : msg['query']
			}, {
				'title' : 'Explain',
				'value' : msg['explain']
			}, {
				'value' : '<%s | go to Cloud Watch Logs>' % (get_logs_URL(event_data_json, executed_at_str))
			}
		]
		response = send_message_to_slack(msg_params, response['ts'])


# 環境変数がセットされているかをチェックする関数
def check_environment_variables(environment_variable_set):
	is_error = False
	for variable in environment_variable_set:
		if os.environ.get(variable) is None:
			print('Error: Please set environment variable \'%s\'.' % (variable))
			is_error = True
	
	return is_error
		

# 遅延の発生時刻（文字列）からログの抽出期間（UNIXタイム）を出力する関数
def make_period_log_extraction(executed_at_str):
	period_log_extraction = int(os.environ.get('PERIOD_LOG_EXTRACTION'))
	executed_at_datetime = datetime.datetime.strptime(executed_at_str ,'%Y-%m-%d %H:%M:%S')

	start_time_log_extraction = calendar.timegm((executed_at_datetime - datetime.timedelta(seconds = period_log_extraction)).utctimetuple()) * 1000
	end_time_log_extraction = calendar.timegm((executed_at_datetime + datetime.timedelta(seconds = period_log_extraction)).utctimetuple()) * 1000

	return start_time_log_extraction, end_time_log_extraction


# クエリログを実行時刻・IP・処理時間・クエリタイプ・実行クエリ・実行計画・処理コストにパースする関数
def parse_query_log(log):
	'''
	クエリログ例：'
		2020-01-01 12:00:00 UTC:100.100.100.100(10000):client_name:[10000]:LOG:  duration: 1234.567 ms plan:\n\t
		Query Text: SELECT * FROM "TEST" WHERE ("id" IN ($1))\n\t
		Gather  (cost=10.00..100.00 rows=20 width=50)\n\tWorkers Planned: 2\n\t->  Parallel Seq Scan on task_logs  (cost=10.00..100.00 rows=20 width=50)
	'
	# パース後変数との対応: '
		{executed_at} UTC:{client_ip}(10000):client_name:[10000]:LOG:  duration: {duration} ms plan:\n\t
		Query Text: {query}
		{explain}
	'
	'''
	executed_at = pattern_datetime.search(log).group()
	client_ip = re.search(r'\d+\.\d+\.\d+\.\d+', log).group()
	duration = re.search(r'(\d+\.\d+) ms', log).group(1)
	query = re.search(r'Query Text: (.*?)[^\n\t]*?\(cost=', log, re.S).group(1)
	explain = re.search(r'Query Text: .*?([^\n\t]*?\(cost=.*)', log, re.S).group(1)

	parsed_msg = {
		'executed_at': convert_utctime_into_localtime(executed_at),
		'client_ip': client_ip,
		'duration': round(float(duration) / 1000, 2),
		'query_type': detect_query_type(query),
		'explain_cost': re.search(r'cost=(\S+)', explain).group(1),
		'query': encase_by_backquote(sqlparse.format(query, reindent=True, keyword_case='upper')),
		'explain': encase_by_backquote(explain)
	}
	identify_info = re.search(r'(.*):LOG', log).group(1)

	return parsed_msg, identify_info


def detect_query_type(query):
	query_type_candidates = ['SELECT', 'INSERT', 'UPDATE', 'DELETE']
	for query_type in query_type_candidates:
		if query_type in query:
			return query_type

	return 'UNKNOWN'


# パラメータログで、実行クエリをパラメータ置換する関数
def parse_parameters_log(param_log, msg_parsed_to):
	'''
	パラメータログ例：'
		2020-01-01 12:00:00 UTC:100.100.100.100(10000):client_name:[10000]:DETAIL:  parameters: $1 = '105'
	'
	'''
	msg_parsed = copy.deepcopy(msg_parsed_to)
	param_set = re.search(r'parameters: (.*)', param_log).group(1).split(', ')

	for param in param_set:
		param_num = re.search(r'\$(\d+)\s', param).group(1)
		param_val = re.search(r'=(.*)', param).group(1).strip()
		msg_parsed = msg_parsed.replace('$' + param_num, param_val, 1)
	
	return msg_parsed


# str型のUTC時刻を、ローカル設定したTZでの時刻へ変換する関数
def convert_utctime_into_localtime(utctime_str):
	if not pattern_datetime.fullmatch(utctime_str).group():
		return 'datetime format error.'

	local_tz = pytz.timezone(os.environ.get('TZ'))
	utctime_aware = datetime.datetime.strptime(utctime_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo = pytz.utc)
	localtime_str = local_tz.normalize(utctime_aware.astimezone(local_tz)).strftime('%Y-%m-%d %H:%M:%S')

	return '%s  (%s)' % (localtime_str, os.environ.get('TZ'))


def encase_by_backquote(message):
	return '```' + message + '```'


def send_message_to_slack(msg_params, thread_ts = ''):
	SLACK_URL = 'https://slack.com/api/chat.postMessage'

	send_data = {
		'username': msg_params['username'],
		'icon_emoji': msg_params['icon_emoji'],
		'token': os.environ.get('SLACK_API_TOKEN'),
		'channel': os.environ.get('SLACK_CHANNEL_ID'),
		'attachments': json.dumps([msg_params['attachments']]),
		'thread_ts': thread_ts
	}

	with requests.post(SLACK_URL, data = send_data) as response:
		return response.json()


#CloudWatch Logsにある該当ログへのリンクを生成する関数
def get_logs_URL(event_data, executed_at):
	cloudwatch_logs_domain = \
		'https://%s.console.aws.amazon.com/cloudwatch/home?region=%s#logsV2:log-groups/log-group/'\
		% (os.environ.get('CLOUDWATCH_REGION'), os.environ.get('CLOUDWATCH_REGION'))
	log_group = urllib.parse.quote_plus(urllib.parse.quote_plus(event_data['logGroup']))
	event_stream = '/log-events/' + urllib.parse.quote_plus(urllib.parse.quote_plus(event_data['logStream']))
	filter_pattern = urllib.parse.quote_plus('?filterPattern=' + urllib.parse.quote_plus('"%s"' % (executed_at)), safe='+')

	logs_URL = (cloudwatch_logs_domain + log_group + event_stream + filter_pattern).replace('%', '$')
	return logs_URL


def make_slack_icon(query_type):
	if query_type == 'SELECT':
		return ':mag:'
	elif query_type == 'INSERT':
		return ':inbox_tray:'
	elif query_type == 'UPDATE':
		return ':recycle:'
	elif query_type == 'DELETE':
		return ':wave:'
	else:
		return ':bento:'


def make_slack_color(duration):
	if duration > float(os.environ.get('NOTIFICATION_COLOR_STANDARD')):
		return 'danger'
	else:
		return 'warning'