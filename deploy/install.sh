#!/bin/bash
# robot_nl_controller のデプロイスクリプト
# 使い方: sudo bash deploy/install.sh

set -e

INSTALL_DIR=/opt/robot_nl_controller
CONFIG_DIR=/etc/robot_nl
SERVICE_FILE=deploy/robot-nl.service

echo "=== robot_nl_controller インストール ==="

# 1. インストールディレクトリ作成
echo "[1/5] ファイルをコピー..."
mkdir -p "$INSTALL_DIR"
cp -r . "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/main.py"

# 2. 設定ディレクトリ作成
echo "[2/5] 設定ディレクトリを作成..."
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    cp config.yaml "$CONFIG_DIR/config.yaml"
    echo "  → $CONFIG_DIR/config.yaml を作成しました。内容を確認してください。"
fi
if [ ! -f "$CONFIG_DIR/secrets.env" ]; then
    cp deploy/secrets.env.example "$CONFIG_DIR/secrets.env"
    chmod 600 "$CONFIG_DIR/secrets.env"
    echo "  → $CONFIG_DIR/secrets.env を作成しました。GCP情報を記入してください。"
fi

# 3. Python 依存パッケージのインストール
echo "[3/5] Python パッケージをインストール..."
pip3 install -r requirements.txt

# 4. systemd サービスをインストール
echo "[4/5] systemd サービスを登録..."
cp "$SERVICE_FILE" /etc/systemd/system/robot-nl.service
systemctl daemon-reload
systemctl enable robot-nl.service

# 5. 完了
echo "[5/5] インストール完了"
echo ""
echo "次のステップ:"
echo "  1. $CONFIG_DIR/secrets.env に GCP 情報を記入"
echo "  2. $CONFIG_DIR/config.yaml の robot.mode を 'real' に変更"
echo "  3. gcloud auth application-default login で認証"
echo "  4. sudo systemctl start robot-nl"
echo "  5. sudo journalctl -u robot-nl -f でログ確認"
