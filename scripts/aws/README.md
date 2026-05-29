# EC2 장중 자동 Start/Stop (KST)

**목표:** 평일 **08:55 KST** EC2 Start → `market_watch` 자동 실행 → **15:40 KST** EC2 Stop (EOD 15:35 빌드 여유).

인스턴스가 꺼져 있으면 `skip (장외)` 루프도 없어 **EC2 시간 요금 절감**.

> 공휴일·임시 휴장은 EventBridge가 모릅니다. 필요 시 AWS 콘솔에서 해당 날 스케줄만 일시 중지하세요.

---

## 0. 한 번만 — EC2에서 market_watch 부팅 자동 실행

인스턴스가 **켜져 있을 때** SSH:

```bash
cd ~/자동매매
git pull   # 이 디렉터리·service 파일 최신

sudo cp scripts/aws/ec2-auto-trade.service /etc/systemd/system/
# 경로가 다르면:
# sudo sed -i "s|/home/ec2-user/자동매매|$(pwd)|" /etc/systemd/system/ec2-auto-trade.service

sudo systemctl daemon-reload
sudo systemctl enable ec2-auto-trade.service
sudo systemctl start ec2-auto-trade.service
systemctl status ec2-auto-trade.service
```

이후 **Lambda가 Start만 하면** 1~2분 뒤 `market_watch`가 알아서 올라갑니다. `nohup` 수동 실행은 불필요.

---

## 1. AWS 준비 (Mac 또는 CloudShell)

변수 설정 (본인 값으로):

```bash
export AWS_REGION=ap-northeast-2          # 서울 리전 예
export INSTANCE_ID=i-xxxxxxxxxxxxxxxxx      # EC2 콘솔에서 복사
export FN_NAME=auto-trade-ec2-scheduler
export ROLE_NAME=auto-trade-ec2-scheduler-role
```

### 1-1) Lambda IAM 역할

```bash
cat > /tmp/trust-lambda.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
EOF

aws iam create-role --role-name "$ROLE_NAME" \
  --assume-role-policy-document file:///tmp/trust-lambda.json

aws iam attach-role-policy --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

cat > /tmp/ec2-start-stop.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["ec2:StartInstances", "ec2:StopInstances", "ec2:DescribeInstances"],
    "Resource": "arn:aws:ec2:${AWS_REGION}:*:instance/${INSTANCE_ID}"
  }]
}
EOF

aws iam put-role-policy --role-name "$ROLE_NAME" \
  --policy-name ec2-start-stop-one \
  --policy-document file:///tmp/ec2-start-stop.json

export ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)
echo "$ROLE_ARN"
```

### 1-2) Lambda 배포

프로젝트 루트에서:

```bash
cd scripts/aws
zip -j /tmp/auto-trade-ec2.zip ec2_scheduler_lambda.py

aws lambda create-function \
  --function-name "$FN_NAME" \
  --runtime python3.11 \
  --role "$ROLE_ARN" \
  --handler ec2_scheduler_lambda.handler \
  --zip-file fileb:///tmp/auto-trade-ec2.zip \
  --timeout 30 \
  --environment "Variables={INSTANCE_ID=$INSTANCE_ID}" \
  --region "$AWS_REGION"
```

이미 있으면:

```bash
aws lambda update-function-code --function-name "$FN_NAME" \
  --zip-file fileb:///tmp/auto-trade-ec2.zip --region "$AWS_REGION"
```

Lambda ARN:

```bash
export LAMBDA_ARN=$(aws lambda get-function --function-name "$FN_NAME" \
  --query Configuration.FunctionArn --output text --region "$AWS_REGION")
```

### 1-3) EventBridge Scheduler → Lambda 호출 역할

```bash
export SCHEDULER_ROLE=auto-trade-scheduler-invoke-role

cat > /tmp/trust-scheduler.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "scheduler.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
EOF

aws iam create-role --role-name "$SCHEDULER_ROLE" \
  --assume-role-policy-document file:///tmp/trust-scheduler.json

cat > /tmp/invoke-lambda.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "lambda:InvokeFunction",
    "Resource": "$LAMBDA_ARN"
  }]
}
EOF

aws iam put-role-policy --role-name "$SCHEDULER_ROLE" \
  --policy-name invoke-lambda \
  --policy-document file:///tmp/invoke-lambda.json

export SCHEDULER_ROLE_ARN=$(aws iam get-role --role-name "$SCHEDULER_ROLE" \
  --query Role.Arn --output text)
```

### 1-4) 스케줄 생성 (타임존 Asia/Seoul)

```bash
# 평일 08:55 KST — Start (장 5분 전 워밍업)
aws scheduler create-schedule \
  --name auto-trade-ec2-start-kst \
  --schedule-expression "cron(55 8 ? * MON-FRI *)" \
  --schedule-expression-timezone "Asia/Seoul" \
  --flexible-time-window Mode=OFF \
  --target "Arn=$LAMBDA_ARN,RoleArn=$SCHEDULER_ROLE_ARN,Input={\"action\":\"start\"}" \
  --region "$AWS_REGION"

# 평일 15:40 KST — Stop (15:35 EOD 빌드 후)
aws scheduler create-schedule \
  --name auto-trade-ec2-stop-kst \
  --schedule-expression "cron(40 15 ? * MON-FRI *)" \
  --schedule-expression-timezone "Asia/Seoul" \
  --flexible-time-window Mode=OFF \
  --target "Arn=$LAMBDA_ARN,RoleArn=$SCHEDULER_ROLE_ARN,Input={\"action\":\"stop\"}" \
  --region "$AWS_REGION"
```

**15:30 정각 Stop**을 원하면 stop cron을 `cron(30 15 ? * MON-FRI *)` 로 바꾸세요 (EOD HTML 자동 생성은 그날 생략될 수 있음).

---

## 2. 동작 확인

```bash
# 수동 Start 테스트
aws lambda invoke --function-name "$FN_NAME" \
  --payload '{"action":"start"}' /tmp/out.json --region "$AWS_REGION" && cat /tmp/out.json

# 2~3분 후 EC2 SSH → systemctl status ec2-auto-trade

# 수동 Stop 테스트 (장외)
aws lambda invoke --function-name "$FN_NAME" \
  --payload '{"action":"stop"}' /tmp/out.json --region "$AWS_REGION"
```

---

## 3. 비용·주의

- **Stop** = 인스턴스 시간 요금 중단 (EBS·Elastic IP는 별도).
- Stop 상태에서는 SSH·자동매매 불가 → Start 스케줄에만 의존.
- **DRY_RUN=false** 실매매 — Start 후 systemd가 곧바로 `market_watch` 실행.
- 공휴일에 Start 되면 `skip (장외)`만 반복 → 그날도 Stop 스케줄 전까지 소량 과금. 공휴일 스케줄 disable 권장.

---

## 4. 수동 nohup 중지 (systemd 전환 시)

```bash
pkill -9 -f market_watch.py || true
sudo systemctl enable --now ec2-auto-trade.service
```
