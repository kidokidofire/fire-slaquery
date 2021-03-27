# Slow Query Notification

Amazon CloudWatch Logsに記録されたSlow QueryをSlackに通知するLambda関数

## 概要

Amazon RDS PostgreSQLでは、処理が遅いクエリの実行計画をCloudWatch Logsに記録することができる。
本プロジェクトは、CloudWatch Logsに記録された遅延クエリログをトリガーとして起動し、
パースしてSlackに通知するLambda関数を構築する。

## 使用方法

### RDS側の準備

1. [ログを通知したいRDSインスタンスのauto_explainを有効にする](https://aws.amazon.com/jp/premiumsupport/knowledge-center/rds-postgresql-tune-query-performance/)

2. [CloudWatch LogsへのPostgreSQLログの発行を設定する](https://docs.aws.amazon.com/ja_jp/AmazonRDS/latest/UserGuide/USER_LogAccess.Concepts.PostgreSQL.html#USER_LogAccess.Concepts.PostgreSQL.PublishtoCloudWatchLogs)

### Lambda関数の構築

#### 1. [AWS SAM](https://docs.aws.amazon.com/ja_jp/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)をインストールする

[認証情報の設定](https://docs.aws.amazon.com/ja_jp/serverless-application-model/latest/developerguide/serverless-getting-started-set-up-credentials.html)が必要なので注意。

#### 2. clone

```bash
> git clone レポジトリURL
> cd slow-query-notification
```

#### 3. AWS SAMとCloudFormationの設定ファイルを変更する

- samconfig.toml
  - stack_name, s3_bucket, s3_prefix は必要に応じて変更
  - region にはLambda関数を構築するAWSリージョンを指定
- template.yaml
  - コメントアウトされている箇所は修正が必須です。
  - CloudWatch LogsのログストリームARN
  - CloudWatch Logsのロググループ名
  - 環境変数を設定
    - TZ: タイムゾーン('Asia/Tokyo')
    - CLOUDWATCH_REGION: 通知したいログが存在するリージョン
    - SLACK_API_TOKEN: SlackアプリのAPIトークン
    - SLACK_CHANNEL_ID: 通知したいSlackチャンネルのID
    - POSTPONEMENT_BEFORE_LOG_EXTRACTION: ログ取得失敗時の待機時間（秒）
    - MAX_RETRY_COUNT_GET_LOG: ログ再取得実行の上限回数
    - PERIOD_LOG_EXTRACTION: ログ取得時間の幅（秒）
    - NOTIFICATION_COLOR_STANDARD: Slack通知色を決めるクエリ実行時間の基準値（秒）

#### 4. AWS Lambdaにビルド＆デプロイ

```bash
> sam build
> sam deploy
```

## ファイル構成

```bash
├── slow_query_notification
│   ├── __init__.py
│   ├── app.py　:　lambda関数を定義
│   └── requirements.txt　:　デプロイパッケージに含めるモジュールを定義
├── tests
├── __init__.py
├── .gitignore
├── README.md
├── samconfig.toml　： AWS SAMの設定ファイル
└── template.yaml　 ： CloudFormationのテンプレートファイル
```
