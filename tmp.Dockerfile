FROM alpine:3.20
RUN <<'EOF'
cat <<'PY' > /tmp/test.py
import sys
print('hello from heredoc')
PY
python3 /tmp/test.py
EOF