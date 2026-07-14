# Music Tagger 🎵

Organizador de biblioteca musical para DJs — servidor local com interface web.

## Funcionalidades

- Lê tags reais dos arquivos (MP3, FLAC, M4A)
- Busca capas via iTunes
- Reconhecimento via Shazam
- Organiza por pastas/gêneros
- Salva tags e capas nos arquivos originais
- Filtra por nome, artista, capa, duração etc
- Multi-seleção com ⌘+clique
- Player integrado

## Instalação

```bash
pip3 install mutagen static-ffmpeg
```

## Uso

```bash
python3 music_server.py --pasta "/caminho/da/sua/pasta"
```

Abre em: http://localhost:8080
