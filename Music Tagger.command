#!/bin/bash
# Music Tagger - Iniciador com Auto-Update
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PASTA="/Users/gustavo.ambrosio/Documents/PENDRIVE DJ Backup Flat 2"
REPO="https://raw.githubusercontent.com/guzambrosio/music-tagger/main/music_server.py"
VERSION_URL="https://raw.githubusercontent.com/guzambrosio/music-tagger/main/version.txt"
LOCAL_VERSION_FILE="$DIR/.music_tagger_version"

echo "================================"
echo "   Music Tagger"
echo "================================"

# Verifica dependências
python3 -c "import mutagen" 2>/dev/null || pip3 install mutagen --quiet
python3 -c "import static_ffmpeg" 2>/dev/null || pip3 install static-ffmpeg --quiet

# Verifica atualização
echo "Verificando atualizações..."
REMOTE_VERSION=$(curl -s --max-time 5 "$VERSION_URL" 2>/dev/null)
LOCAL_VERSION=$(cat "$LOCAL_VERSION_FILE" 2>/dev/null || echo "0")

if [ ! -z "$REMOTE_VERSION" ] && [ "$REMOTE_VERSION" != "$LOCAL_VERSION" ]; then
  echo "Nova versão disponível: $REMOTE_VERSION (atual: $LOCAL_VERSION)"
  echo "Atualizando..."
  
  # Faz backup
  [ -f "$DIR/music_server.py" ] && cp "$DIR/music_server.py" "$DIR/music_server_backup.py"
  
  # Baixa nova versão
  curl -s "$REPO" -o "$DIR/music_server.py"
  
  if [ $? -eq 0 ]; then
    echo "$REMOTE_VERSION" > "$LOCAL_VERSION_FILE"
    echo "✓ Atualizado para versão $REMOTE_VERSION!"
  else
    echo "Erro ao atualizar, usando versão local."
    [ -f "$DIR/music_server_backup.py" ] && cp "$DIR/music_server_backup.py" "$DIR/music_server.py"
  fi
else
  echo "✓ Versão atual: $LOCAL_VERSION"
fi

echo ""

# Verifica se music_server.py existe
if [ ! -f "$DIR/music_server.py" ]; then
  osascript -e 'display dialog "music_server.py não encontrado!\n\nVerifique sua conexão com a internet." buttons {"OK"} default button "OK" with icon stop'
  exit 1
fi

# Inicia servidor
python3 "$DIR/music_server.py" --pasta "$PASTA"
