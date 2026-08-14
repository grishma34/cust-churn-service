#!/usr/bin/env bash
# Post-deploy smoke checklist (PLAN.md Phase 4). Usage:
#   scripts/smoke.sh [FUNCTION_URL]
# With no argument, reads the FunctionUrl output of the deployed stack.
# Exits non-zero on any failure, so it can gate a pipeline.
set -euo pipefail

STACK="${STACK_NAME:-cust-churn-service}"
URL="${1:-$(aws cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='FunctionUrl'].OutputValue" --output text)}"
URL="${URL%/}"

PASS=0
FAIL=0
note() { printf '%s\n' "$*"; }
check() { # check <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    PASS=$((PASS + 1)); note "  ok: $1"
  else
    FAIL=$((FAIL + 1)); note "  FAIL: $1 (expected $2, got $3)"
  fi
}
json() { python3 -c "import json,sys; print(json.load(sys.stdin)$2)" <<<"$1"; }

PAYLOAD='{"gender":"Female","SeniorCitizen":0,"Partner":"Yes","Dependents":"No",
"tenure":5,"PhoneService":"Yes","MultipleLines":"No","InternetService":"Fiber optic",
"OnlineSecurity":"No","OnlineBackup":"No","DeviceProtection":"No","TechSupport":"No",
"StreamingTV":"Yes","StreamingMovies":"No","Contract":"Month-to-month",
"PaperlessBilling":"Yes","PaymentMethod":"Electronic check",
"MonthlyCharges":85.7,"TotalCharges":420.35}'

note "smoke: $URL"

# 1-2: health
HEALTH=$(curl -s "$URL/health")
check "GET /health status ok" "ok" "$(json "$HEALTH" "['status']")"
MODEL_VERSION=$(json "$HEALTH" "['model_version']")
check "health carries a model version" "yes" "$([ -n "$MODEL_VERSION" ] && echo yes)"

# 3-4: model metadata
MODEL=$(curl -s "$URL/model")
check "GET /model version matches health" "$MODEL_VERSION" "$(json "$MODEL" "['model_version']")"
check "model metadata has a threshold" "yes" \
  "$(python3 -c "import json;m=json.loads('''$MODEL''');print('yes' if 0<m['threshold']<1 else 'no')")"

# 5-8: predict happy path
PREDICT=$(curl -s -X POST "$URL/predict" -H 'Content-Type: application/json' -d "$PAYLOAD")
PREDICTION_ID=$(json "$PREDICT" "['prediction_id']")
check "POST /predict returns a prediction id" "yes" "$([ -n "$PREDICTION_ID" ] && echo yes)"
check "prediction carries the model version" "$MODEL_VERSION" "$(json "$PREDICT" "['model_version']")"
check "probability in [0,1]" "yes" \
  "$(python3 -c "import json;p=json.loads('''$PREDICT''');print('yes' if 0<=p['churn_probability']<=1 else 'no')")"
check "decision consistent with threshold" "yes" \
  "$(python3 -c "import json;p=json.loads('''$PREDICT''');print('yes' if p['churn_predicted']==(p['churn_probability']>=p['threshold']) else 'no')")"

# 9-11: error contract
check "invalid body is 400" "400" \
  "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/predict" -d '{"tenure": -1}')"
check "unknown path is 404" "404" "$(curl -s -o /dev/null -w '%{http_code}' "$URL/nope")"
check "GET /predict is 405" "405" "$(curl -s -o /dev/null -w '%{http_code}' "$URL/predict")"

# 12-13: the audit trail really received the prediction (REQ-0011), traceable
# to the same model version (REQ-0010)
TABLE=$(aws cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='TableName'].OutputValue" --output text)
sleep 2
ITEM=$(aws dynamodb get-item --table-name "$TABLE" \
  --key "{\"PK\":{\"S\":\"PRED#$PREDICTION_ID\"},\"SK\":{\"S\":\"META\"}}" --output json)
check "prediction logged to DynamoDB" "yes" \
  "$(python3 -c "import json;print('yes' if 'Item' in json.loads('''$ITEM''') else 'no')")"
check "audit item carries the same model version" "$MODEL_VERSION" \
  "$(json "$ITEM" "['Item']['modelVersion']['S']")"

note ""
note "smoke: $PASS/$((PASS + FAIL)) passed"
[ "$FAIL" -eq 0 ]
