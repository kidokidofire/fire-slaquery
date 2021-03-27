import sys, os
sys.path.append('../')
os.environ['TZ'] = 'Asia/Tokyo'

from slow_query_notification.app import parse_query_log, parse_parameters_log


def test_parse_query_log_1():
	test_log = '\
		2020-01-01 12:00:00 UTC:100.100.100.100(10000):client_name:[10000]:LOG:  duration: 1234.567 ms plan:\n\t\
		Query Text: SELECT * FROM "TEST" WHERE ("id" IN ($1))\n\t\
		Gather  (cost=10.00..100.00 rows=20 width=50)\n\tWorkers Planned: 2\n\t->  Parallel Seq Scan on task_logs  (cost=10.00..100.00 rows=20 width=50)\
	'
	parsed_query_log = parse_query_log(test_log)[0]

	assert parsed_query_log.get('executed_at') == '2020-01-01 21:00:00  (Asia/Tokyo)'
	assert parsed_query_log.get('client_ip') == '100.100.100.100'
	assert parsed_query_log.get('duration') == 1.23
	assert parsed_query_log.get('query_type') == 'SELECT'
	assert parsed_query_log.get('explain_cost') == '10.00..100.00'
	assert parsed_query_log.get('query') == '```SELECT *\nFROM "TEST"\nWHERE ("id" IN ($1))```'
	assert parsed_query_log.get('explain') == '```Gather  (cost=10.00..100.00 rows=20 width=50)\n\tWorkers Planned: 2\n\t->  Parallel Seq Scan on task_logs  (cost=10.00..100.00 rows=20 width=50)\t```'


def test_parse_query_log_2():
	test_log = '\
		2020-01-01 12:00:00 UTC:100.100.100.100(10000):client_name:[10000]:LOG:  duration: 1234.567 ms plan:\n\t\
		Query Text: /* sample comment */\nSELECT * FROM "TEST" WHERE ("id" IN ($1))\n\t\
		Gather  (cost=10.00..100.00 rows=20 width=50)\n\tWorkers Planned: 2\n\t->  Parallel Seq Scan on task_logs  (cost=10.00..100.00 rows=20 width=50)\
	'
	parsed_query_log = parse_query_log(test_log)[0]

	assert parsed_query_log.get('executed_at') == '2020-01-01 21:00:00  (Asia/Tokyo)'
	assert parsed_query_log.get('client_ip') == '100.100.100.100'
	assert parsed_query_log.get('duration') == 1.23
	assert parsed_query_log.get('query_type') == 'SELECT'
	assert parsed_query_log.get('explain_cost') == '10.00..100.00'
	assert parsed_query_log.get('query') == '```/* sample comment */\nSELECT *\nFROM "TEST"\nWHERE ("id" IN ($1))```'
	assert parsed_query_log.get('explain') == '```Gather  (cost=10.00..100.00 rows=20 width=50)\n\tWorkers Planned: 2\n\t->  Parallel Seq Scan on task_logs  (cost=10.00..100.00 rows=20 width=50)\t```'


def test_parse_parameters_log():
	test_log = "\
		2020-01-01 12:00:00 UTC:100.100.100.100(10000):client_name:[10000]:DETAIL:  \
		parameters: $1 = '105'\
	"
	test_msg = '```SELECT *\nFROM "TEST"\nWHERE ("id" IN ($1))```'
	
	parsed_query_text = '```SELECT *\nFROM "TEST"\nWHERE ("id" IN (\'105\'))```'

	assert parse_parameters_log(test_log, test_msg) == parsed_query_text