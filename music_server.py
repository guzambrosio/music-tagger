#!/usr/bin/env python3
"""
Music Tagger Server
-------------------
Roda um servidor local que integra o Music Tagger com a pasta real do Mac.

Uso:
    python3 music_server.py
    python3 music_server.py --pasta "/Users/gustavo.ambrosio/Documents/PENDRIVE DJ"

Abre no navegador: http://localhost:8080
"""

import os, sys, json, shutil, hashlib, threading, urllib.request, time, subprocess, struct, base64
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

try:
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, ID3NoHeaderError
    from mutagen.flac import FLAC, Picture
    from mutagen.mp4 import MP4, MP4Cover
    MUTAGEN_OK = True
except ImportError:
    MUTAGEN_OK = False
    print("AVISO: pip3 install mutagen para gravar tags")

EXTENSOES = {'.mp3', '.flac', '.wav', '.aac', '.ogg', '.m4a', '.opus', '.wma'}
PASTA_PADRAO = Path("/Users/gustavo.ambrosio/Documents/PENDRIVE DJ")
STATE_FILE = Path.home() / ".music_tagger_state.json"

pasta_atual = PASTA_PADRAO

# ── UTILITÁRIOS ───────────────────────────────────────────────────────────────
LIXO_TAGS = ['spotdown.org','SpotiDost','KLICKAUD','forhub Soundcloud to mp3',
    'forhub Soundcloud','SpotiDownloader.com','spotidownloader.com','spotifydown.com',
    'SpotiDown.App','FREE DL','Free DL','Free Download','FREE DOWNLOAD',
    'Official Music Video','Official Video','.mp3','.mp4']

def limpar_tag(texto):
    import re
    if not texto: return ''
    for l in LIXO_TAGS:
        texto = texto.replace(l, '').replace(l.upper(), '').replace(l.lower(), '')
    texto = re.sub(r'https?://\S+', '', texto)
    texto = re.sub(r'\s+', ' ', texto).strip(' .-_[]')
    return texto

def ler_tags_mp3(caminho):
    try:
        tags = ID3(str(caminho))
        titulo  = limpar_tag(str(tags.get('TIT2', '')))
        artista = limpar_tag(str(tags.get('TPE1', '')))
        album   = limpar_tag(str(tags.get('TALB', '')))
        import base64
        cover = None
        # Tenta todos os tipos de APIC
        for k in list(tags.keys()):
            if k.startswith('APIC'):
                apic = tags[k]
                try:
                    mime = getattr(apic, 'mime', 'image/jpeg') or 'image/jpeg'
                    if apic.data and len(apic.data) > 5000:
                        b64 = base64.b64encode(apic.data).decode()
                        cover = 'data:' + mime + ';base64,' + b64
                except Exception:
                    pass
                break
        return titulo, artista, album, cover
    except Exception:
        return '', '', '', None

def ler_tags_flac(caminho):
    try:
        audio = FLAC(str(caminho))
        import base64
        titulo  = limpar_tag(' '.join(audio.get('title',[])))
        artista = limpar_tag(' '.join(audio.get('artist',[])))
        album   = limpar_tag(' '.join(audio.get('album',[])))
        cover = None
        pics = audio.pictures
        if pics and len(pics[0].data) > 5000:
            mime = pics[0].mime or 'image/jpeg'
            b64 = base64.b64encode(pics[0].data).decode()
            cover = 'data:' + mime + ';base64,' + b64
        return titulo, artista, album, cover
    except Exception:
        return '', '', '', None

def ler_tags_m4a(caminho):
    try:
        audio = MP4(str(caminho))
        import base64
        titulo  = limpar_tag(' '.join(audio.get('\xa9nam', [])))
        artista = limpar_tag(' '.join(audio.get('\xa9ART', [])))
        album   = limpar_tag(' '.join(audio.get('\xa9alb', [])))
        cover = None
        covr = audio.get('covr')
        if covr and len(bytes(covr[0])) > 5000:
            fmt = covr[0].imageformat
            mime = 'image/png' if fmt == MP4Cover.FORMAT_PNG else 'image/jpeg'
            b64 = base64.b64encode(bytes(covr[0])).decode()
            cover = 'data:' + mime + ';base64,' + b64
        return titulo, artista, album, cover
    except Exception:
        return '', '', '', None

def ler_tags(caminho):
    if not MUTAGEN_OK:
        return '', '', '', None
    ext = caminho.suffix.lower()
    if ext == '.mp3':
        return ler_tags_mp3(caminho)
    elif ext == '.flac':
        return ler_tags_flac(caminho)
    elif ext in ('.m4a', '.aac'):
        return ler_tags_m4a(caminho)
    return '', '', '', None

def nome_para_artista_titulo(filename):
    import re
    nome = re.sub(r'\.[^.]+$', '', filename)
    nome = re.sub(r'^\d+[_.\-\s]+', '', nome)
    nome = nome.replace('_', ' ').strip()
    if ' - ' in nome:
        partes = nome.split(' - ', 1)
        return partes[0].strip(), partes[1].strip()
    return '', nome

def listar_musicas(pasta):
    musicas = []
    for f in sorted(pasta.rglob('*')):
        if f.is_file() and f.suffix.lower() in EXTENSOES:
            titulo, artista, album, cover = ler_tags(f)
            # Fallback: infere do nome do arquivo
            if not titulo or not artista:
                a_nome, t_nome = nome_para_artista_titulo(f.name)
                if not artista: artista = a_nome
                if not titulo:  titulo  = t_nome
            # Se o arquivo está direto na raiz da pasta selecionada, é "Sem pasta"
            # Se está em subpasta imediata, usa o nome da subpasta como folder
            # Se está mais fundo (sub-subpasta), ainda usa a subpasta imediata
            rel = f.relative_to(pasta)
            parts = rel.parts
            folder = parts[0] if len(parts) > 1 else 'Sem pasta'
            # Lê duração
            duracao = 0
            try:
                if MUTAGEN_OK and f.suffix.lower() == '.mp3':
                    from mutagen.mp3 import MP3 as _MP3
                    duracao = int(_MP3(str(f)).info.length)
                elif MUTAGEN_OK and f.suffix.lower() == '.flac':
                    duracao = int(FLAC(str(f)).info.length)
                elif MUTAGEN_OK and f.suffix.lower() in ('.m4a','.aac'):
                    duracao = int(MP4(str(f)).info.length)
            except Exception:
                pass
            musicas.append({
                'filename': f.name,
                'path': str(f),
                'folder': folder,
                'title':  titulo,
                'artist': artista,
                'album':  album,
                'cover':  cover,
                'duration': duracao,
            })
    return musicas

def listar_pastas(pasta):
    pastas = set()
    for f in pasta.iterdir():
        if f.is_dir():
            pastas.add(f.name)
    return sorted(list(pastas))

def get_ffmpeg():
    """Retorna caminho do ffmpeg (static-ffmpeg ou sistema)."""
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
    except Exception:
        pass
    # Tenta ffmpeg do sistema primeiro
    for cmd in ['ffmpeg', '/usr/local/bin/ffmpeg', '/opt/homebrew/bin/ffmpeg']:
        try:
            subprocess.run([cmd, '-version'], capture_output=True, timeout=5)
            return cmd
        except Exception:
            pass
    return None

def shazam_recognize(caminho):
    """Reconhece música via Shazam usando ffmpeg para extrair trecho de áudio."""
    import time as t

    try:
        ffmpeg = get_ffmpeg()
        if not ffmpeg:
            return {'error': 'ffmpeg não disponível'}

        # Extrai 5s a partir de 30s como WAV mono 44100Hz
        tmp = Path('/tmp/shazam_sample.wav')
        ret = subprocess.run([
            ffmpeg, '-y', '-ss', '30', '-i', str(caminho),
            '-t', '5', '-ar', '44100', '-ac', '1',
            '-f', 'wav', str(tmp)
        ], capture_output=True, timeout=30)

        if ret.returncode != 0 or not tmp.exists():
            # Tenta do início se falhar
            ret = subprocess.run([
                ffmpeg, '-y', '-i', str(caminho),
                '-t', '5', '-ar', '44100', '-ac', '1',
                '-f', 'wav', str(tmp)
            ], capture_output=True, timeout=30)

        if not tmp.exists():
            return None

        audio_data = tmp.read_bytes()
        tmp.unlink()

        # Envia para Shazam
        url = 'https://api.shazam.com/discovery/v5/detect'
        req = urllib.request.Request(
            url,
            data=audio_data,
            headers={
                'Content-Type': 'audio/wav; charset=utf-8',
                'Accept': 'application/json',
                'X-Shazam-Platform': 'IPHONE',
                'X-Shazam-AppVersion': '14.1.0',
                'X-Shazam-Country': 'BR',
                'X-Shazam-Locale': 'pt-BR',
            },
            method='POST'
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        track = data.get('track')
        if not track:
            return None

        result = {
            'title':  track.get('title', ''),
            'artist': track.get('subtitle', ''),
            'album':  '',
            'cover':  None,
        }

        for sec in track.get('sections', []):
            if sec.get('type') == 'SONG':
                for meta in sec.get('metadata', []):
                    if meta.get('title') == 'Album':
                        result['album'] = meta.get('text', '')

        images = track.get('images', {})
        cover_url = images.get('coverarthq') or images.get('coverart')
        if cover_url:
            result['cover'] = cover_url

        return result

    except Exception as e:
        print('Shazam error: ' + str(e))
        return None

def ffmpeg_disponivel():
    return get_ffmpeg() is not None

def baixar_imagem(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.read()
    except Exception:
        return None

def aplicar_tags_com_dados(caminho, titulo, artista, album, cover_url=None, cover_data=None):
    """Aplica tags e capa. cover_data tem prioridade sobre cover_url."""
    if not MUTAGEN_OK:
        return False
    if cover_data is None and cover_url:
        cover_data = baixar_imagem(cover_url)
    return _gravar_tags(caminho, titulo, artista, album, cover_data)

def aplicar_tags(caminho, titulo, artista, album, cover_url):
    if not MUTAGEN_OK:
        return False
    capa_data = baixar_imagem(cover_url) if cover_url else None
    return _gravar_tags(caminho, titulo, artista, album, capa_data)

def _gravar_tags(caminho, titulo, artista, album, capa_data):
    ext = Path(caminho).suffix.lower()
    try:
        if ext == '.mp3':
            try: tags = ID3(caminho)
            except ID3NoHeaderError: tags = ID3()
            for key in list(tags.keys()):
                if key[:4] not in ['TIT2','TPE1','TALB','APIC']:
                    try: del tags[key]
                    except: pass
            if titulo:  tags['TIT2'] = TIT2(encoding=3, text=titulo)
            if artista: tags['TPE1'] = TPE1(encoding=3, text=artista)
            if album:   tags['TALB'] = TALB(encoding=3, text=album)
            if capa_data:
                tags['APIC'] = APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=capa_data)
            tags.save(caminho)
        elif ext == '.flac':
            audio = FLAC(caminho)
            audio.clear(); audio.clear_pictures()
            if titulo:  audio['title']  = titulo
            if artista: audio['artist'] = artista
            if album:   audio['album']  = album
            if capa_data:
                pic = Picture(); pic.type = 3; pic.mime = 'image/jpeg'; pic.data = capa_data
                audio.add_picture(pic)
            audio.save()
        elif ext in ('.m4a', '.aac'):
            audio = MP4(caminho)
            audio.clear()
            if titulo:  audio['\xa9nam'] = [titulo]
            if artista: audio['\xa9ART'] = [artista]
            if album:   audio['\xa9alb'] = [album]
            if capa_data:
                audio['covr'] = [MP4Cover(capa_data, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()
        return True
    except Exception as e:
        print("Erro ao salvar tags: " + str(e))
        return False

def mover_arquivo(caminho_atual, pasta_destino_nome):
    caminho = Path(caminho_atual)
    destino_pasta = pasta_atual / pasta_destino_nome
    if caminho.parent.resolve() == destino_pasta.resolve():
        return caminho_atual
    destino_pasta.mkdir(parents=True, exist_ok=True)
    dest = destino_pasta / caminho.name
    c = 1
    while dest.exists():
        dest = destino_pasta / (caminho.stem + '_' + str(c) + caminho.suffix)
        c += 1
    shutil.move(str(caminho), str(dest))
    return str(dest)

# ── ESTADO ───────────────────────────────────────────────────────────────────
def salvar_estado(dados):
    with open(str(STATE_FILE), 'w') as f:
        json.dump(dados, f)

def carregar_estado():
    if STATE_FILE.exists():
        with open(str(STATE_FILE)) as f:
            return json.load(f)
    return None

# ── HTML ──────────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Music Tagger</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Space+Mono:wght@400;700&display=swap');
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  :root{--bg:#0e0e0f;--surface:#171718;--surface2:#1f1f21;--border:#2a2a2d;--accent:#c8f060;--accent2:#60c8f0;--text:#e8e8ea;--muted:#6b6b70;--danger:#f06060;--radius:8px}
  body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);height:100vh;display:grid;grid-template-rows:56px 1fr 90px;overflow:hidden}
  header{display:flex;align-items:center;justify-content:space-between;padding:0 20px;border-bottom:1px solid var(--border);background:var(--surface)}
  .logo{font-family:'Space Mono',monospace;font-size:12px;font-weight:700;letter-spacing:.15em;color:var(--accent);text-transform:uppercase;white-space:nowrap}
  .pasta-badge{font-size:10px;color:var(--muted);font-family:'Space Mono',monospace;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .header-actions{display:flex;gap:6px;align-items:center}
  .workspace{display:grid;grid-template-columns:240px 1fr 300px;overflow:hidden}
  /* SIDEBAR */
  .sidebar{border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden;background:var(--surface)}
  .sidebar-header{padding:12px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
  .sidebar-title{font-size:11px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
  .folders-list{flex:1;overflow-y:auto;padding:6px}
  .folder-item{display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:var(--radius);cursor:pointer;font-size:13px;transition:background .15s;user-select:none;position:relative}
  .folder-item:hover{background:var(--surface2)}
  .folder-item.active{background:var(--surface2);color:var(--accent)}
  .folder-item .fi{font-size:13px;flex-shrink:0}
  .folder-item .fn{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .folder-item .fc{font-size:10px;color:var(--muted);font-family:'Space Mono',monospace}
  .folder-item.drop-target{outline:2px solid var(--accent)}
  .folder-actions{display:none;gap:3px;align-items:center}
  .folder-item:hover .folder-actions{display:flex}
  .folder-btn{background:none;border:none;cursor:pointer;padding:2px 5px;border-radius:4px;font-size:11px;line-height:1}
  .folder-btn.rename{color:var(--accent2)}.folder-btn.rename:hover{background:rgba(96,200,240,.15)}
  .folder-btn.del{color:var(--danger)}.folder-btn.del:hover{background:rgba(240,96,96,.15)}
  /* MAIN */
  .main{display:flex;flex-direction:column;overflow:hidden}
  .main-toolbar{padding:10px 14px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  .filter-select{background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);padding:6px 8px;font-size:12px;color:var(--text);font-family:inherit;outline:none;cursor:pointer;flex-shrink:0}
  .filter-select:focus{border-color:var(--accent)}
  .filter-select option{background:var(--surface2);color:var(--text)}
  .search-input{flex:1;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);padding:6px 12px;font-size:13px;color:var(--text);font-family:inherit;outline:none}
  .search-input:focus{border-color:var(--accent)}
  .selection-bar{padding:5px 14px;font-size:11px;border-bottom:1px solid var(--border);display:none;align-items:center;gap:10px;background:rgba(200,240,96,.05)}
  .selection-bar.active{display:flex}
  .save-progress{padding:5px 14px;font-size:11px;color:var(--muted);border-bottom:1px solid var(--border);display:none;align-items:center;gap:10px}
  .save-progress.active{display:flex}
  .save-bar{flex:1;height:2px;background:var(--border);border-radius:2px}
  .save-fill{height:100%;background:var(--accent);border-radius:2px;transition:width .3s}
  .stats-bar{padding:5px 14px;font-size:11px;color:var(--muted);border-bottom:1px solid var(--border);display:flex;gap:14px;font-family:'Space Mono',monospace}
  .stats-bar span{color:var(--accent)}
  .track-list{flex:1;overflow-y:auto}
  .track-item{display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--border);cursor:pointer;transition:background .1s;user-select:none}
  .track-item:hover{background:var(--surface)}
  .track-item.selected-primary{background:var(--surface2);border-left:2px solid var(--accent);padding-left:12px}
  .track-item.selected-multi{background:rgba(200,240,96,.08);border-left:2px solid var(--accent);padding-left:12px}
  .track-item.playing{border-left:2px solid var(--accent2);padding-left:12px}
  .track-item.dirty-mark .track-title::after{content:' •';color:var(--accent);font-size:10px}
  .track-cover{width:42px;height:42px;border-radius:4px;background:var(--surface2);flex-shrink:0;overflow:hidden;display:flex;align-items:center;justify-content:center;font-size:17px;position:relative}
  .track-cover img{width:100%;height:100%;object-fit:cover}
  .play-overlay{position:absolute;inset:0;background:rgba(0,0,0,.55);display:none;align-items:center;justify-content:center;font-size:15px;border-radius:4px}
  .track-item:hover .play-overlay{display:flex}
  .track-info{flex:1;min-width:0}
  .track-title{font-size:13px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .track-sub{font-size:11px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:2px}
  .track-folder-badge{font-size:10px;padding:2px 7px;border-radius:20px;background:var(--surface2);color:var(--muted);white-space:nowrap;font-family:'Space Mono',monospace}
  /* DETAIL */
  .detail{border-left:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden;background:var(--surface)}
  .detail-empty{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--muted);font-size:13px;gap:8px;padding:24px;text-align:center}
  .detail-scroll{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px}
  /* EDIT SECTION FIRST */
  .detail-section-title{font-size:10px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
  .field{display:flex;flex-direction:column;gap:4px}
  .field label{font-size:10px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
  .field input{background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);padding:7px 10px;font-size:13px;color:var(--text);font-family:inherit;outline:none;width:100%}
  .field input:focus{border-color:var(--accent)}
  /* COVER */
  .detail-cover-wrap{width:100%;aspect-ratio:1;border-radius:var(--radius);background:var(--surface2);overflow:hidden;display:flex;align-items:center;justify-content:center;font-size:48px;position:relative}
  .detail-cover-wrap img{width:100%;height:100%;object-fit:cover}
  .cover-badge{position:absolute;bottom:6px;right:6px;font-size:10px;padding:2px 7px;border-radius:20px;background:rgba(0,0,0,.75);color:var(--accent);font-family:'Space Mono',monospace}
  /* TAG DISPLAY */
  .tag-display{background:var(--surface2);border-radius:var(--radius);padding:10px 12px;display:flex;flex-direction:column;gap:3px;border:1px solid var(--border)}
  .tag-row{display:flex;align-items:baseline;gap:6px}
  .tag-label{font-size:9px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);min-width:42px;flex-shrink:0}
  .tag-value{font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
  .tag-value.empty{color:var(--muted);font-style:italic}
  /* FOLDER CHIPS */
  .folder-chips{display:flex;flex-wrap:wrap;gap:5px}
  .folder-chip{font-size:11px;padding:4px 10px;border-radius:20px;border:1px solid var(--border);background:var(--surface2);cursor:pointer;transition:all .15s;font-family:inherit;color:var(--text)}
  .folder-chip:hover{border-color:var(--accent);color:var(--accent)}
  .folder-chip.current{border-color:var(--accent);background:rgba(200,240,96,.1);color:var(--accent)}
  /* MULTI SELECTION PANEL */
  .multi-panel{flex:1;display:flex;flex-direction:column;overflow-y:auto;padding:16px;gap:12px}
  .multi-cover-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:4px}
  .mini-cover{width:100%;aspect-ratio:1;border-radius:4px;background:var(--surface2);overflow:hidden;display:flex;align-items:center;justify-content:center;font-size:14px}
  .mini-cover img{width:100%;height:100%;object-fit:cover}
  /* PLAYER */
  .player{border-top:1px solid var(--border);background:var(--surface);display:flex;align-items:center;gap:14px;padding:0 20px}
  .player-cover{width:50px;height:50px;border-radius:6px;background:var(--surface2);overflow:hidden;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0}
  .player-cover img{width:100%;height:100%;object-fit:cover}
  .player-info{flex:0 0 150px;min-width:0}
  .player-title{font-size:12px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .player-artist{font-size:11px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:1px}
  .player-controls{display:flex;align-items:center;gap:4px}
  .player-btn{background:none;border:none;cursor:pointer;color:var(--muted);font-size:17px;padding:5px;border-radius:6px;line-height:1}
  .player-btn:hover{color:var(--text)}
  .player-btn.pp{color:var(--accent);font-size:22px}
  .player-progress{flex:1;display:flex;align-items:center;gap:8px}
  .player-time{font-size:10px;color:var(--muted);font-family:'Space Mono',monospace;white-space:nowrap;min-width:30px;text-align:center}
  .progress-bar{flex:1;height:4px;background:var(--border);border-radius:2px;cursor:pointer}
  .progress-fill{height:100%;background:var(--accent);border-radius:2px;width:0%}
  .player-volume{display:flex;align-items:center;gap:5px}
  .vol-slider{width:65px;accent-color:var(--accent);cursor:pointer}
  .player-genre{font-size:10px;padding:2px 8px;border-radius:20px;border:1px solid var(--border);color:var(--accent2);font-family:'Space Mono',monospace;white-space:nowrap}
  /* BTNS */
  .btn{display:inline-flex;align-items:center;gap:5px;padding:6px 12px;border-radius:var(--radius);border:none;cursor:pointer;font-size:12px;font-weight:500;font-family:inherit;transition:all .15s;white-space:nowrap}
  .btn-primary{background:var(--accent);color:#0e0e0f}.btn-primary:hover{background:#d8ff70}
  .btn-ghost{background:transparent;color:var(--muted);border:1px solid var(--border)}.btn-ghost:hover{color:var(--text);border-color:var(--text)}
  .btn-danger{background:transparent;color:var(--danger);border:1px solid var(--danger)}.btn-danger:hover{background:rgba(240,96,96,.1)}
  .btn-accent2{background:transparent;color:var(--accent2);border:1px solid var(--accent2)}.btn-accent2:hover{background:rgba(96,200,240,.1)}
  .btn-sm{padding:4px 9px;font-size:11px}
  .btn-icon{padding:5px;border-radius:6px;background:transparent;color:var(--muted);border:1px solid var(--border);cursor:pointer;font-size:13px;transition:all .15s}.btn-icon:hover{color:var(--text);border-color:var(--text)}
  /* MODALS */
  .modal-overlay{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.75);z-index:9999;align-items:center;justify-content:center}
  .modal-overlay.open{display:flex}
  .modal{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:24px;width:420px;min-width:320px;display:flex;flex-direction:column;gap:16px;position:relative;z-index:10000}
  .modal h3{font-size:15px;font-weight:600}
  .modal p{font-size:13px;color:var(--muted)}
  .modal-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:4px}
  .modal{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:22px;width:400px;display:flex;flex-direction:column;gap:14px}
  .modal h3{font-size:15px;font-weight:600}.modal p{font-size:13px;color:var(--muted)}
  .modal-actions{display:flex;gap:8px;justify-content:flex-end}
  .modal-input{background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);padding:8px 10px;font-size:13px;color:var(--text);font-family:inherit;outline:none;width:100%}
  .modal-input:focus{border-color:var(--accent)}
  /* TAG PREVIEW MODAL */
  .tag-preview-list{display:flex;flex-direction:column;gap:6px}
  .tag-preview-item{background:var(--surface2);border-radius:var(--radius);padding:10px 12px;border:2px solid var(--border);display:flex;gap:10px;align-items:center;cursor:pointer;transition:all .15s;user-select:none}
  .tag-preview-item:hover{border-color:var(--muted)}
  .tag-preview-item.selected{border-color:var(--accent);background:rgba(200,240,96,.07)}
  .tag-preview-item.checked-item{border-color:var(--accent);background:rgba(200,240,96,.07)}
  .tag-preview-cover{width:52px;height:52px;border-radius:6px;background:var(--bg);flex-shrink:0;overflow:hidden;display:flex;align-items:center;justify-content:center;font-size:20px;border:1px solid var(--border)}
  .tag-preview-cover img{width:100%;height:100%;object-fit:cover}
  .tag-preview-info{flex:1;min-width:0}
  .tag-preview-title{font-size:13px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .tag-preview-sub{font-size:11px;color:var(--muted);margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .tag-preview-check{flex-shrink:0}
  .tag-preview-check input{accent-color:var(--accent);width:18px;height:18px;cursor:pointer}
  .tag-loading{padding:32px;text-align:center;color:var(--muted);font-size:13px}
  /* TOAST */
  .toast{position:fixed;bottom:104px;left:50%;transform:translateX(-50%) translateY(80px);background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:9px 16px;font-size:13px;z-index:200;transition:transform .2s,opacity .2s;pointer-events:none;opacity:0}
  .toast.show{transform:translateX(-50%) translateY(0);opacity:1}
  .toast.success{border-color:var(--accent);color:var(--accent)}
  ::-webkit-scrollbar{width:4px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}
</style>
</head>
<body>
<header>
  <div style="display:flex;align-items:center;gap:10px;min-width:0">
    <div class="logo">Music Tagger</div>
    <span class="pasta-badge" id="pastaBadge">carregando...</span>
  </div>
  <div class="header-actions">
    <button class="btn btn-ghost btn-sm" onclick="selecionarPasta()">📁 Pasta</button>
    <button class="btn btn-ghost btn-sm" onclick="recarregarPasta()">↺ Recarregar</button>
    <button class="btn btn-ghost btn-sm" onclick="limparTags()">✂ Limpar tags</button>
    <button class="btn btn-ghost btn-sm" onclick="limparCapasRuins()">🖼 Limpar capas ruins</button>
    <button class="btn btn-ghost btn-sm" onclick="shazamEmLote()">🎵 Shazam em lote</button>
    <button class="btn btn-accent2 btn-sm" onclick="fetchAllCovers()">⬇ Buscar capas</button>
    <button class="btn btn-primary btn-sm" onclick="salvarTudo()">💾 Salvar alterados</button>
  </div>
</header>
<div class="workspace">
  <aside class="sidebar">
    <div class="sidebar-header">
      <span class="sidebar-title">Pastas</span>
      <button class="btn-icon" onclick="openNewFolderModal()">＋</button>
    </div>
    <div class="folders-list" id="foldersList"></div>
  </aside>
  <main class="main">
    <div class="main-toolbar">
      <input class="search-input" type="text" placeholder="Buscar título, artista ou álbum..." id="searchInput" oninput="filterTracks()">
      <select id="sortSelect" class="filter-select" onchange="applySortFilter()">
        <option value="title_az">⇅ Nome A→Z</option>
        <option value="title_za">⇅ Nome Z→A</option>
        <option value="artist_az">⇅ Artista A→Z</option>
        <option value="artist_za">⇅ Artista Z→A</option>
        <option value="dur_asc">⇅ Menor duração</option>
        <option value="dur_desc">⇅ Maior duração</option>
        <option value="folder_az">⇅ Pasta A→Z</option>
      </select>
      <select id="filterSelect" class="filter-select" onchange="applySortFilter()">
        <option value="all">☰ Todas</option>
        <option value="no_cover">☰ Sem capa</option>
        <option value="with_cover">☰ Com capa</option>
        <option value="no_title">☰ Sem título</option>
        <option value="no_artist">☰ Sem artista</option>
        <option value="dirty">☰ Alteradas</option>
        <option value="sem_pasta">☰ Sem pasta</option>
      </select>
    </div>
    <div class="selection-bar" id="selectionBar">
      <span id="selectionCount" style="color:var(--accent);font-family:'Space Mono',monospace"></span>
      <span style="color:var(--muted)">selecionadas</span>
      <button class="btn btn-ghost btn-sm" onclick="clearSelection()">✕ Limpar</button>
      <button class="btn btn-accent2 btn-sm" onclick="fetchMultiCovers()">♫ Buscar capas</button>
      <label class="btn btn-ghost btn-sm" style="cursor:pointer">
        🖼 Upload capa
        <input type="file" accept="image/*" style="display:none" onchange="uploadMultiCover(event)">
      </label>
    </div>
    <div class="save-progress" id="saveProgress">
      <span id="saveProgressText">Salvando...</span>
      <div class="save-bar"><div class="save-fill" id="saveFill"></div></div>
      <span id="saveProgressCount" style="font-family:'Space Mono',monospace;font-size:10px;color:var(--muted)"></span>
    </div>
    <div class="stats-bar">
      <div>Total: <span id="statTotal">0</span></div>
      <div>Sem pasta: <span id="statUnassigned">0</span></div>
      <div>Com capa: <span id="statCovers">0</span></div>
      <div>Alterados: <span id="statDirty">0</span></div>
    </div>
    <div class="track-list" id="trackList"></div>
  </main>
  <aside class="detail">
    <div class="detail-empty" id="detailEmpty"><div style="font-size:32px;opacity:.4">🎵</div><div>Selecione uma música</div><div style="font-size:11px;color:var(--muted);margin-top:4px">⌘+clique para selecionar múltiplas</div></div>
    <!-- SINGLE SELECTION -->
    <div class="detail-scroll" id="detailContent" style="display:none">
      <!-- 1. CAPA PRIMEIRO -->
      <div>
        <div class="detail-section-title">Capa</div>
        <div style="position:relative">
          <div class="detail-cover-wrap" id="detailCoverWrap"><span style="font-size:48px">🎵</span></div>
          <button id="removeCoverBtn" onclick="removeCover()" style="display:none;position:absolute;top:8px;left:8px;background:rgba(240,96,96,.9);border:none;border-radius:6px;color:white;font-size:11px;padding:3px 7px;cursor:pointer;font-family:inherit">✕</button>
        </div>
        <label class="btn btn-ghost btn-sm" style="cursor:pointer;width:100%;justify-content:center;margin-top:6px">
          🖼 Upload capa
          <input type="file" accept="image/*" style="display:none" onchange="uploadSingleCover(event)">
        </label>
      </div>
      <!-- 2. EDIÇÃO -->
      <div>
        <div class="detail-section-title">Editar</div>
        <div style="display:flex;flex-direction:column;gap:8px">
          <div class="field"><label>Título</label><input type="text" id="fieldTitle" placeholder="Nome da música" oninput="markDirty()" onkeydown="if(event.key==='Enter')applyEdit()"></div>
          <div class="field"><label>Artista</label><input type="text" id="fieldArtist" placeholder="Nome do artista" oninput="markDirty()" onkeydown="if(event.key==='Enter')applyEdit()"></div>
          <div class="field"><label>Álbum</label><input type="text" id="fieldAlbum" placeholder="Nome do álbum" oninput="markDirty()" onkeydown="if(event.key==='Enter')applyEdit()"></div>
        </div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn btn-accent2 btn-sm" onclick="fetchSpotify()" style="flex:1">♫ Buscar tags</button>
        <button class="btn btn-ghost btn-sm" onclick="shazamRecognize()" title="Reconhece pelo áudio via Shazam" style="flex:1">🎵 Shazam</button>
        <button class="btn btn-ghost btn-sm" onclick="applyEdit()" style="width:100%">✓ Aplicar</button>
      </div>
      <!-- 3. MOVER PARA PASTA -->
      <div>
        <div class="detail-section-title">Mover para pasta</div>
        <div class="folder-chips" id="folderChips"></div>
      </div>
      <!-- 4. TAGS ATUAIS POR ÚLTIMO -->
      <div>
        <div class="detail-section-title">Tags atuais no arquivo</div>
        <div class="tag-display">
          <div class="tag-row"><span class="tag-label">Título</span><span class="tag-value" id="tagTitle">—</span></div>
          <div class="tag-row"><span class="tag-label">Artista</span><span class="tag-value" id="tagArtist">—</span></div>
          <div class="tag-row"><span class="tag-label">Álbum</span><span class="tag-value" id="tagAlbum">—</span></div>
          <div class="tag-row"><span class="tag-label">Pasta</span><span class="tag-value" id="tagFolder">—</span></div>
        </div>
      </div>
      <div style="display:flex;gap:6px">
        <button class="btn btn-danger btn-sm" style="flex:1" onclick="removeTrack()">✕ Remover da lista</button>
        <button class="btn btn-danger btn-sm" onclick="deleteTrackFile()" title="Apagar arquivo do disco permanentemente" style="background:rgba(240,96,96,.15)">🗑 Apagar arquivo</button>
      </div>
    </div>
    <!-- MULTI SELECTION -->
    <div class="multi-panel" id="multiPanel" style="display:none">
      <div style="font-size:13px;font-weight:500" id="multiTitle">Múltiplas selecionadas</div>
      <div class="multi-cover-grid" id="multiCoverGrid"></div>
      <div>
        <div class="detail-section-title" style="margin-bottom:6px">Mover todas para pasta</div>
        <div class="folder-chips" id="multiFolderChips"></div>
      </div>
      <div style="display:flex;flex-direction:column;gap:6px">
        <button class="btn btn-accent2 btn-sm" onclick="fetchMultiCovers()">♫ Buscar capas das selecionadas</button>
        <label class="btn btn-ghost btn-sm" style="cursor:pointer;justify-content:center">
          🖼 Upload capa para todas
          <input type="file" accept="image/*" style="display:none" onchange="uploadMultiCover(event)">
        </label>
        <button class="btn btn-danger btn-sm" onclick="removeSelected()">✕ Remover selecionadas</button>
      </div>
    </div>
  </aside>
</div>
<div class="player">
  <div class="player-cover" id="playerCover">🎵</div>
  <div class="player-info">
    <div class="player-title" id="playerTitle">Nenhuma música</div>
    <div class="player-artist" id="playerArtist">—</div>
  </div>
  <div class="player-controls">
    <button class="player-btn" onclick="prevTrack()">⏮</button>
    <button class="player-btn pp" id="playPauseBtn" onclick="togglePlay()">▶</button>
    <button class="player-btn" onclick="nextTrack()">⏭</button>
  </div>
  <div class="player-progress">
    <span class="player-time" id="currentTime">0:00</span>
    <div class="progress-bar" id="progressBar" onclick="seekTo(event)"><div class="progress-fill" id="progressFill"></div></div>
    <span class="player-time" id="totalTime">0:00</span>
  </div>
  <div class="player-volume">
    <span style="font-size:13px;color:var(--muted)">🔊</span>
    <input type="range" class="vol-slider" min="0" max="1" step="0.01" value="0.8" oninput="setVolume(this.value)">
  </div>
  <span class="player-genre" id="playerGenre">—</span>
  <audio id="audioPlayer" onended="nextTrack()" ontimeupdate="updateProgress()" onloadedmetadata="updateDuration()"></audio>
</div>

<!-- MODAL NOVA/RENOMEAR PASTA -->
<div class="modal-overlay" id="folderModal">
  <div class="modal">
    <h3 id="folderModalTitle">Nova pasta</h3>
    <div class="field">
      <label>Nome</label>
      <input class="modal-input" type="text" id="folderModalInput" placeholder="ex: HOUSE, HIP-HOP...">
    </div>
    <div class="modal-actions">
      <button class="btn btn-ghost" onclick="closeModal('folderModal')">Cancelar</button>
      <button class="btn btn-primary" id="folderModalBtn" onclick="confirmFolderModal()">✓ OK</button>
    </div>
  </div>
</div>

<!-- MODAL APAGAR PASTA -->
<div class="modal-overlay" id="deleteFolderModal">
  <div class="modal">
    <h3>Apagar pasta</h3>
    <p id="deleteFolderMsg"></p>
    <div class="modal-actions">
      <button class="btn btn-ghost" onclick="closeModal('deleteFolderModal')">Cancelar</button>
      <button class="btn btn-danger" onclick="confirmDeleteFolder()">✕ Apagar</button>
    </div>
  </div>
</div>

<!-- MODAL PRÉVIA DE TAGS -->
<div class="modal-overlay" id="tagPreviewModal">
  <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:22px;width:560px;max-height:75vh;display:flex;flex-direction:column;gap:14px;position:relative;z-index:10001">
    <div>
      <h3 id="tagPreviewTitle" style="font-size:15px;font-weight:600;margin-bottom:4px">Prévia das tags encontradas</h3>
      <p id="tagPreviewSubtitle" style="font-size:12px;color:var(--muted)">Clique para selecionar</p>
    </div>
    <div id="tagPreviewList" style="overflow-y:auto;display:flex;flex-direction:column;gap:8px;min-height:60px;max-height:420px;padding-right:4px"></div>
    <div style="display:flex;align-items:center;gap:8px;padding-top:10px;border-top:1px solid var(--border);flex-shrink:0">
      <button class="btn btn-ghost btn-sm" id="toggleAllBtn" onclick="toggleAllPreviews()" style="display:none">Marcar/desmarcar todos</button>
      <div style="margin-left:auto;display:flex;gap:8px">
        <button class="btn btn-ghost" onclick="closeModal('tagPreviewModal')">Cancelar</button>
        <button class="btn btn-primary" onclick="applyTagPreviews()">✓ OK</button>
      </div>
    </div>
  </div>
</div>

<!-- MODAL APAGAR ARQUIVO -->
<div class="modal-overlay" id="deleteFileModal">
  <div class="modal">
    <h3>🗑 Apagar arquivo do disco</h3>
    <p id="deleteFileMsg">Este arquivo será apagado permanentemente. Esta ação não pode ser desfeita.</p>
    <div class="modal-actions">
      <button class="btn btn-ghost" onclick="closeModal('deleteFileModal')">Cancelar</button>
      <button class="btn btn-danger" onclick="confirmDeleteFile()">🗑 Apagar</button>
    </div>
  </div>
</div>

<!-- MODAL SELECIONAR PASTA -->
<div class="modal-overlay" id="pastaModal">
  <div class="modal">
    <h3>📁 Selecionar pasta</h3>
    <p>Digite o caminho completo da pasta de músicas:</p>
    <div class="field">
      <label>Caminho</label>
      <input class="modal-input" type="text" id="pastaInput" placeholder="/Users/gustavo.ambrosio/Documents/PENDRIVE DJ Backup Flat 2" autocomplete="off">
    </div>
    <div class="modal-actions">
      <button class="btn btn-ghost" onclick="closeModal('pastaModal')">Cancelar</button>
      <button class="btn btn-primary" onclick="confirmPasta()">✓ OK</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let tracks = [], folders = [], selectedId = null, playingId = null, sortDir = 1;
let dirty = {};
let selectedIds = new Set(); // multi-selection
let folderModalMode = 'create'; // 'create' | 'rename'
let folderToRename = null;
let folderToDelete = null;
let tagPreviews = []; // pending tag results
const audio = document.getElementById('audioPlayer');
audio.volume = 0.8;

const LIXO = ['spotdown.org','SpotiDost','KLICKAUD','forhub Soundcloud to mp3',
  'SpotiDownloader.com','spotidownloader.com','spotifydown.com','SpotiDown.App',
  'FREE DL','Free DL','Free Download','FREE DOWNLOAD','.mp3','.mp4','[SPOTDOWNLOADER.COM]'];

function limparTexto(t) {
  if (!t) return '';
  LIXO.forEach(l => { t = t.replace(new RegExp(l.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'gi'),''); });
  return t.replace(/\s+/g,' ').trim().replace(/^[\s.\-_]+|[\s.\-_]+$/g,'');
}

async function api(endpoint, method='GET', body=null) {
  const opts = {method, headers:{'Content-Type':'application/json'}};
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch('/api/' + endpoint, opts);
  return r.json();
}

async function init() {
  const state = await api('state');
  tracks = state.tracks || [];
  folders = state.folders || [];
  document.getElementById('pastaBadge').textContent = state.pasta || '';
  renderFolders(); renderTracks(); filterByFolder('Todas');
}

async function recarregarPasta() {
  showToast('Lendo pasta...');
  const data = await api('scan');
  tracks = data.tracks; folders = data.folders; dirty = {}; selectedIds.clear(); selectedId = null;
  document.getElementById('pastaBadge').textContent = data.pasta;
  resetDetail();
  renderFolders(); renderTracks(); filterByFolder('Todas');
  showToast(tracks.length + ' músicas carregadas', 'success');
}

async function selecionarPasta() {
  document.getElementById('pastaInput').value = document.getElementById('pastaBadge').textContent || '/Users/gustavo.ambrosio/Documents/PENDRIVE DJ Backup Flat 2';
  document.getElementById('pastaModal').classList.add('open');
  setTimeout(()=>document.getElementById('pastaInput').focus(),100);
}

async function confirmPasta() {
  const nome = document.getElementById('pastaInput').value.trim();
  if (!nome) return;
  closeModal('pastaModal');
  const data = await api('set-pasta', 'POST', {pasta: nome});
  if (data.ok) await recarregarPasta();
  else showToast('Pasta não encontrada');
}

function resetDetail() {
  document.getElementById('detailEmpty').style.display = 'flex';
  document.getElementById('detailContent').style.display = 'none';
  document.getElementById('multiPanel').style.display = 'none';
}

// ── FOLDERS ───────────────────────────────────────────────────────────────────
function renderFolders() {
  const list = document.getElementById('foldersList');
  const counts = {};
  folders.forEach(f => counts[f] = 0);
  tracks.forEach(t => { if (counts[t.folder] !== undefined) counts[t.folder]++; else counts['Sem pasta'] = (counts['Sem pasta']||0)+1; });
  list.innerHTML = ['Todas', ...folders].map(f => {
    const count = f === 'Todas' ? tracks.length : (counts[f] || 0);
    const icon = f === 'Todas' ? '◈' : f === 'Sem pasta' ? '◌' : '▸';
    const canEdit = f !== 'Todas' && f !== 'Sem pasta';
    return `<div class="folder-item" data-folder="${f}" onclick="filterByFolder('${f}')"
      ondragover="event.preventDefault();this.classList.add('drop-target')"
      ondragleave="this.classList.remove('drop-target')"
      ondrop="dropToFolder(event,'${f}')">
      <span class="fi">${icon}</span><span class="fn">${f}</span><span class="fc">${count}</span>
      ${canEdit ? `<div class="folder-actions">
        <button class="folder-btn rename" onclick="event.stopPropagation();openRenameFolder('${f}')" title="Renomear">✏</button>
        <button class="folder-btn del" onclick="event.stopPropagation();openDeleteFolder('${f}')" title="Apagar">✕</button>
      </div>` : ''}
    </div>`;
  }).join('');
}

let filterFolder = 'Todas', filterSearch = '';
function getVisibleTracks() {
  return getFilteredSortedTracks(tracks);
}

function updateStats() {
  document.getElementById('statTotal').textContent = tracks.length;
  document.getElementById('statUnassigned').textContent = tracks.filter(t=>!t.folder||t.folder==='Sem pasta').length;
  document.getElementById('statCovers').textContent = tracks.filter(t=>t.cover).length;
  document.getElementById('statDirty').textContent = Object.values(dirty).filter(Boolean).length;
  const bar = document.getElementById('selectionBar');
  if (selectedIds.size > 1) {
    bar.classList.add('active');
    document.getElementById('selectionCount').textContent = selectedIds.size;
  } else {
    bar.classList.remove('active');
  }
}

function renderTracks() {
  const list = document.getElementById('trackList');
  const visible = getVisibleTracks();
  list.innerHTML = visible.map(t => {
    const isMulti = selectedIds.has(t.id);
    const isPrimary = t.id === selectedId && !isMulti;
    return `<div class="track-item ${isPrimary?'selected-primary':''} ${isMulti?'selected-multi':''} ${t.id===playingId?'playing':''} ${dirty[t.id]?'dirty-mark':''}"
      draggable="true" ondragstart="event.dataTransfer.setData('trackId','${t.id}')"
      onclick="handleTrackClick(event,'${t.id}')">
      <div class="track-cover">
        ${t.cover ? `<img src="${t.cover}" onerror="this.style.display='none'">` : '🎵'}
        <div class="play-overlay" onclick="event.stopPropagation();playTrack('${t.id}')">▶</div>
      </div>
      <div class="track-info">
        <div class="track-title">${t.title || t.filename}</div>
        <div class="track-sub">${t.artist||'—'} · ${t.album||'—'}${t.duration ? ' · ' + Math.floor(t.duration/60) + ':' + String(t.duration%60).padStart(2,'0') : ''}</div>
      </div>
      <span class="track-folder-badge">${t.folder||'Sem pasta'}</span>
    </div>`;
  }).join('') || '<div style="padding:32px;text-align:center;color:var(--muted);font-size:13px">Nenhuma música</div>';
  updateStats();
}

function filterByFolder(f) {
  filterFolder = f;
  document.querySelectorAll('.folder-item').forEach(el => el.classList.toggle('active', el.dataset.folder === f));
  renderTracks();
}
function filterTracks() { filterSearch = document.getElementById('searchInput').value; applySortFilter(); }

function applySortFilter() {
  filterSearch = document.getElementById('searchInput').value;
  renderTracks();
}

function getFilteredSortedTracks(base) {
  const sortVal   = document.getElementById('sortSelect')?.value || 'title_az';
  const filterVal = document.getElementById('filterSelect')?.value || 'all';

  // Filtra por pasta/busca
  let result = base.filter(t => {
    const mf = filterFolder === 'Todas' || t.folder === filterFolder;
    const q = filterSearch.toLowerCase();
    return mf && (!q || (t.title||'').toLowerCase().includes(q) || (t.artist||'').toLowerCase().includes(q) || (t.album||'').toLowerCase().includes(q) || t.filename.toLowerCase().includes(q));
  });

  // Filtro adicional
  if (filterVal === 'no_cover')   result = result.filter(t => !t.cover);
  if (filterVal === 'with_cover') result = result.filter(t => !!t.cover);
  if (filterVal === 'no_title')   result = result.filter(t => !t.title);
  if (filterVal === 'no_artist')  result = result.filter(t => !t.artist);
  if (filterVal === 'dirty')      result = result.filter(t => dirty[t.id]);
  if (filterVal === 'sem_pasta')  result = result.filter(t => !t.folder || t.folder === 'Sem pasta');

  // Ordenação
  result.sort((a, b) => {
    switch(sortVal) {
      case 'title_az':  return (a.title||a.filename).localeCompare(b.title||b.filename);
      case 'title_za':  return (b.title||b.filename).localeCompare(a.title||a.filename);
      case 'artist_az': return (a.artist||'').localeCompare(b.artist||'');
      case 'artist_za': return (b.artist||'').localeCompare(a.artist||'');
      case 'dur_asc':   return (a.duration||0) - (b.duration||0);
      case 'dur_desc':  return (b.duration||0) - (a.duration||0);
      case 'folder_az': return (a.folder||'').localeCompare(b.folder||'');
      default: return 0;
    }
  });

  return result;
}

// ── SELECTION ─────────────────────────────────────────────────────────────────
function handleTrackClick(event, id) {
  if (event.metaKey || event.ctrlKey) {
    // Multi-select com CMD
    if (selectedIds.has(id)) {
      selectedIds.delete(id);
      if (selectedId === id) selectedId = [...selectedIds][selectedIds.size-1] || null;
    } else {
      selectedIds.add(id);
      selectedId = id;
    }
  } else {
    selectedIds.clear();
    selectedId = id;
  }
  renderTracks();
  updateDetailPanel();
}

function clearSelection() {
  selectedIds.clear();
  renderTracks();
  updateStats();
  if (selectedId) updateDetailPanel();
}

function updateDetailPanel() {
  if (selectedIds.size > 1) {
    showMultiPanel();
  } else if (selectedId) {
    selectedIds.clear();
    selectTrack(selectedId);
  } else {
    resetDetail();
  }
}

function showMultiPanel() {
  document.getElementById('detailEmpty').style.display = 'none';
  document.getElementById('detailContent').style.display = 'none';
  document.getElementById('multiPanel').style.display = 'flex';
  const ids = [...selectedIds];
  document.getElementById('multiTitle').textContent = ids.length + ' músicas selecionadas';
  // Mini covers
  const selected = ids.map(id => tracks.find(t=>t.id===id)).filter(Boolean);
  document.getElementById('multiCoverGrid').innerHTML = selected.slice(0,8).map(t =>
    `<div class="mini-cover">${t.cover ? `<img src="${t.cover}">` : '🎵'}</div>`
  ).join('') + (selected.length > 8 ? `<div class="mini-cover" style="font-size:11px;color:var(--muted)">+${selected.length-8}</div>` : '');
  // Folder chips
  document.getElementById('multiFolderChips').innerHTML = folders.map(f =>
    `<button class="folder-chip" onclick="moveMultiToFolder('${f}')">${f}</button>`
  ).join('');
}

// ── SINGLE TRACK ──────────────────────────────────────────────────────────────
function selectTrack(id) {
  selectedId = id;
  const t = tracks.find(x=>x.id===id);
  if (!t) return;
  document.getElementById('detailEmpty').style.display = 'none';
  document.getElementById('detailContent').style.display = 'flex';
  document.getElementById('multiPanel').style.display = 'none';
  // Tags atuais
  document.getElementById('tagTitle').textContent  = t.title  || '—';
  document.getElementById('tagTitle').className  = 'tag-value' + (t.title  ? '' : ' empty');
  document.getElementById('tagArtist').textContent = t.artist || '—';
  document.getElementById('tagArtist').className = 'tag-value' + (t.artist ? '' : ' empty');
  document.getElementById('tagAlbum').textContent  = t.album  || '—';
  document.getElementById('tagAlbum').className  = 'tag-value' + (t.album  ? '' : ' empty');
  document.getElementById('tagFolder').textContent = t.folder || 'Sem pasta';
  // Campos edição
  document.getElementById('fieldTitle').value  = t.title  || '';
  document.getElementById('fieldArtist').value = t.artist || '';
  document.getElementById('fieldAlbum').value  = t.album  || '';
  // Capa
  const wrap = document.getElementById('detailCoverWrap');
  const btn  = document.getElementById('removeCoverBtn');
  if (t.cover) {
    wrap.innerHTML = `<img src="${t.cover}"><div class="cover-badge">✓ capa</div>`;
    btn.style.display = 'block';
  } else {
    wrap.innerHTML = `<span style="font-size:48px">🎵</span>`;
    btn.style.display = 'none';
  }
  // Folder chips
  document.getElementById('folderChips').innerHTML = folders.map(f =>
    `<button class="folder-chip ${(t.folder||'Sem pasta')===f?'current':''}" onclick="moveTrack('${t.id}','${f}')">${f}</button>`
  ).join('');
  renderTracks();
}

function markDirty() { if (selectedId) dirty[selectedId] = true; updateStats(); }

function applyEdit() {
  if (!selectedId) return;
  const t = tracks.find(x=>x.id===selectedId);
  t.title  = document.getElementById('fieldTitle').value.trim();
  t.artist = document.getElementById('fieldArtist').value.trim();
  t.album  = document.getElementById('fieldAlbum').value.trim();
  dirty[selectedId] = true;
  selectTrack(selectedId);
  if (t.id === playingId) updatePlayerUI(t);
  api('save-state','POST',{tracks,folders});
  showToast('Tags atualizadas', 'success');
}

function moveTrack(id, folder) {
  const t = tracks.find(x=>x.id===id);
  if (!t || t.folder === folder) return;
  t.folder = folder;
  dirty[id] = true;
  renderFolders();
  // Seleciona primeira da lista atual após mover
  const visible = getVisibleTracks();
  if (filterFolder !== 'Todas' && !visible.find(v=>v.id===id)) {
    const first = visible[0];
    if (first) { selectedId = first.id; selectTrack(first.id); }
    else resetDetail();
  } else {
    selectTrack(id);
  }
  renderTracks();
  api('save-state','POST',{tracks,folders});
  showToast('Movido para ' + folder, 'success', 2000);
}

function moveMultiToFolder(folder) {
  [...selectedIds].forEach(id => {
    const t = tracks.find(x=>x.id===id);
    if (t) { t.folder = folder; dirty[id] = true; }
  });
  renderFolders(); renderTracks();
  api('save-state','POST',{tracks,folders});
  showToast(selectedIds.size + ' movidas para ' + folder, 'success', 2000);
  // Seleciona primeira da lista
  const visible = getVisibleTracks();
  selectedIds.clear();
  if (visible[0]) { selectedId = visible[0].id; selectTrack(visible[0].id); }
  else { selectedId = null; resetDetail(); }
  renderTracks();
}

function dropToFolder(event, folder) {
  event.preventDefault();
  document.querySelectorAll('.folder-item').forEach(el=>el.classList.remove('drop-target'));
  const id = event.dataTransfer.getData('trackId');
  if (id) moveTrack(id, folder);
}

function removeCover() {
  if (!selectedId) return;
  const t = tracks.find(x=>x.id===selectedId);
  t.cover = null; dirty[selectedId] = true;
  selectTrack(t.id); renderTracks();
  api('save-state','POST',{tracks,folders});
  showToast('Capa removida', 'success');
}

function removeTrack() {
  if (!selectedId) return;
  const visible = getVisibleTracks();
  const idx = visible.findIndex(t=>t.id===selectedId);
  tracks = tracks.filter(x=>x.id!==selectedId);
  delete dirty[selectedId];
  // Seleciona próxima ou anterior
  const newVisible = getVisibleTracks();
  if (newVisible.length > 0) {
    const nextIdx = Math.min(idx, newVisible.length - 1);
    selectedId = newVisible[nextIdx].id;
    selectTrack(selectedId);
  } else {
    selectedId = null;
    resetDetail();
  }
  renderFolders(); renderTracks();
  api('save-state','POST',{tracks,folders});
  showToast('Removido da lista');
}

function deleteTrackFile() {
  if (!selectedId) return;
  const t = tracks.find(x=>x.id===selectedId);
  if (!t) return;
  document.getElementById('deleteFileMsg').textContent = 'Apagar permanentemente: "' + (t.title || t.filename) + '"? Esta ação não pode ser desfeita.';
  document.getElementById('deleteFileModal').classList.add('open');
}

async function confirmDeleteFile() {
  if (!selectedId) return;
  const t = tracks.find(x=>x.id===selectedId);
  if (!t) return;
  closeModal('deleteFileModal');
  const res = await api('delete-file', 'POST', {path: t.path});
  if (res.ok) {
    // Remove da lista e seleciona próxima
    const visible = getVisibleTracks();
    const idx = visible.findIndex(v=>v.id===selectedId);
    tracks = tracks.filter(x=>x.id!==selectedId);
    delete dirty[selectedId];
    const newVisible = getVisibleTracks();
    if (newVisible.length > 0) {
      const nextIdx = Math.min(idx, newVisible.length-1);
      selectedId = newVisible[nextIdx].id;
      selectTrack(selectedId);
    } else {
      selectedId = null;
      resetDetail();
    }
    renderFolders(); renderTracks();
    api('save-state','POST',{tracks,folders});
    showToast('Arquivo apagado do disco', 'success');
  } else {
    showToast('Erro ao apagar arquivo');
  }
}

function removeSelected() {
  const ids = [...selectedIds];
  tracks = tracks.filter(t => !ids.includes(t.id));
  ids.forEach(id => delete dirty[id]);
  selectedIds.clear(); selectedId = null;
  resetDetail(); renderFolders(); renderTracks();
  api('save-state','POST',{tracks,folders});
  showToast(ids.length + ' removidas da lista');
}

// ── UPLOAD CAPA ───────────────────────────────────────────────────────────────
function uploadSingleCover(event) {
  const file = event.target.files[0];
  if (!file || !selectedId) return;
  const reader = new FileReader();
  reader.onload = e => {
    const t = tracks.find(x=>x.id===selectedId);
    t.cover = e.target.result;
    dirty[selectedId] = true;
    selectTrack(t.id); renderTracks();
    api('save-state','POST',{tracks,folders});
    showToast('Capa aplicada!', 'success');
  };
  reader.readAsDataURL(file);
  event.target.value = '';
}

function uploadMultiCover(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    const ids = selectedIds.size > 1 ? [...selectedIds] : (selectedId ? [selectedId] : []);
    ids.forEach(id => {
      const t = tracks.find(x=>x.id===id);
      if (t) { t.cover = e.target.result; dirty[id] = true; }
    });
    renderTracks();
    if (selectedId) selectTrack(selectedId);
    if (selectedIds.size > 1) showMultiPanel();
    api('save-state','POST',{tracks,folders});
    showToast(ids.length + ' capas aplicadas!', 'success');
  };
  reader.readAsDataURL(file);
  event.target.value = '';
}

// ── FETCH SINGLE COM PRÉVIA ───────────────────────────────────────────────────
async function shazamEmLote() {
  // Pega músicas sem título OU sem artista OU sem capa
  const alvo = tracks.filter(t => !t.title || !t.artist || !t.cover);
  if (!alvo.length) { showToast('Todas as músicas já têm tags!', 'success'); return; }

  const prog = document.getElementById('saveProgress');
  const fill = document.getElementById('saveFill');
  const cnt  = document.getElementById('saveProgressCount');
  document.getElementById('saveProgressText').textContent = '🎵 Shazam em lote...';
  prog.classList.add('active');

  let found = 0, notFound = 0;
  for (let i = 0; i < alvo.length; i++) {
    const t = alvo[i];
    cnt.textContent = (i+1) + '/' + alvo.length + ' — ' + (t.title || t.filename).slice(0,30);
    fill.style.width = Math.round((i+1)/alvo.length*100) + '%';
    try {
      const res = await api('shazam', 'POST', {path: t.path});
      if (res.ok) {
        if (res.title)  t.title  = res.title;
        if (res.artist) t.artist = res.artist;
        if (res.album)  t.album  = res.album;
        if (res.cover)  t.cover  = res.cover;
        dirty[t.id] = true;
        found++;
        if (found % 5 === 0) { renderTracks(); api('save-state','POST',{tracks,folders}); }
      } else { notFound++; }
    } catch(e) { notFound++; }
    // Aguarda entre requests para não sobrecarregar
    await new Promise(r => setTimeout(r, 1000));
  }

  prog.classList.remove('active');
  renderTracks();
  if (selectedId) selectTrack(selectedId);
  api('save-state','POST',{tracks,folders});
  showToast(found + ' reconhecidas, ' + notFound + ' não encontradas', 'success', 4000);
}

async function shazamRecognize() {
  const t = tracks.find(x=>x.id===selectedId);
  if (!t || !t.path) { showToast('Arquivo necessário para reconhecer'); return; }

  // Abre modal com loading
  document.getElementById('tagPreviewTitle').textContent = '🎵 Reconhecendo pelo Shazam...';
  document.getElementById('tagPreviewSubtitle').textContent = t.filename;
  document.getElementById('tagPreviewList').innerHTML = '<div class="tag-loading">🎵 Enviando áudio para o Shazam...</div>';
  document.getElementById('toggleAllBtn').style.display = 'none';
  document.getElementById('tagPreviewModal').classList.add('open');

  try {
    const res = await api('shazam', 'POST', {path: t.path});
    if (res.ok) {
      // Mostra resultado como prévia única
      document.getElementById('tagPreviewTitle').textContent = '🎵 Shazam encontrou!';
      document.getElementById('tagPreviewSubtitle').textContent = 'Confirme se deseja aplicar:';
      tagPreviews = [{
        track: t,
        results: [{
          trackName: res.title,
          artistName: res.artist,
          collectionName: res.album,
          artworkUrl100: res.cover,
        }],
        single: true
      }];
      showTagPreviewModal(tagPreviews);
    } else {
      const msg = res.error === 'ffmpeg não instalado'
        ? 'ffmpeg necessário. Instale com: brew install ffmpeg'
        : 'Shazam não reconheceu esta música';
      document.getElementById('tagPreviewTitle').textContent = 'Não reconhecido';
      document.getElementById('tagPreviewList').innerHTML = '<div class="tag-loading" style="color:var(--danger)">⚠ ' + msg + '</div>';
    }
  } catch(e) {
    document.getElementById('tagPreviewList').innerHTML = '<div class="tag-loading" style="color:var(--danger)">Erro: ' + e.message + '</div>';
  }
}

async function fetchSpotify() {
  const t = tracks.find(x=>x.id===selectedId);
  if (!t) return;
  t.title  = document.getElementById('fieldTitle').value.trim()  || t.title;
  t.artist = document.getElementById('fieldArtist').value.trim() || t.artist;
  const query = [t.artist, t.title].filter(Boolean).join(' ') || t.filename.replace(/\.[^.]+$/,'');
  // Abre modal com loading
  document.getElementById('tagPreviewTitle').textContent = 'Buscando tags...';
  document.getElementById('tagPreviewSubtitle').textContent = query.slice(0,50);
  document.getElementById('tagPreviewList').innerHTML = '<div class="tag-loading">🔍 Buscando resultados...</div>';
  document.getElementById('toggleAllBtn').style.display = 'none';
  document.getElementById('tagPreviewModal').classList.add('open');
  try {
    const res = await fetch(`https://itunes.apple.com/search?term=${encodeURIComponent(query)}&entity=song&limit=5`);
    const data = await res.json();
    if (data.results?.length) {
      tagPreviews = [{track: t, results: data.results, single: true}];
      showTagPreviewModal(tagPreviews);
    } else {
      document.getElementById('tagPreviewTitle').textContent = 'Nenhum resultado';
      document.getElementById('tagPreviewList').innerHTML = '<div class="tag-loading" style="color:var(--danger)">Nenhum resultado encontrado para "' + query.slice(0,40) + '"</div>';
    }
  } catch(e) {
    document.getElementById('tagPreviewList').innerHTML = '<div class="tag-loading" style="color:var(--danger)">Erro na busca</div>';
  }
}

// ── FETCH ALL COM PRÉVIA ──────────────────────────────────────────────────────
async function fetchAllCovers() {
  const sem = tracks.filter(t => !t.cover);
  if (!sem.length) { showToast('Todas já têm capa!', 'success'); return; }
  const prog = document.getElementById('saveProgress');
  const fill = document.getElementById('saveFill');
  const cnt  = document.getElementById('saveProgressCount');
  document.getElementById('saveProgressText').textContent = 'Buscando capas...';
  prog.classList.add('active');
  let found = 0;
  for (let i = 0; i < sem.length; i++) {
    const t = sem[i];
    const query = [t.artist, t.title].filter(Boolean).join(' ') || t.filename.replace(/\.[^.]+$/, '');
    try {
      const res = await fetch(`https://itunes.apple.com/search?term=${encodeURIComponent(query)}&entity=song&limit=1`);
      const data = await res.json();
      if (data.results?.length) {
        const r = data.results[0];
        t.cover  = r.artworkUrl100?.replace('100x100bb','300x300bb') || null;
        if (!t.title  && r.trackName)      t.title  = r.trackName;
        if (!t.artist && r.artistName)     t.artist = r.artistName;
        if (!t.album  && r.collectionName) t.album  = r.collectionName;
        dirty[t.id] = true;
        found++;
      }
    } catch(e) {}
    fill.style.width = Math.round((i+1)/sem.length*100) + '%';
    cnt.textContent  = (i+1) + '/' + sem.length;
    if ((i+1) % 10 === 0) { renderTracks(); if (selectedId) selectTrack(selectedId); }
    await new Promise(r => setTimeout(r, 180));
  }
  prog.classList.remove('active');
  document.getElementById('saveProgressText').textContent = 'Salvando...';
  renderTracks();
  if (selectedId) selectTrack(selectedId);
  api('save-state','POST',{tracks,folders});
  showToast(found + ' capas encontradas e aplicadas!', 'success');
}

async function fetchMultiCovers() {
  const ids = selectedIds.size > 1 ? [...selectedIds] : [];
  if (!ids.length) { showToast('Selecione múltiplas músicas com ⌘+clique'); return; }
  const selected = ids.map(id=>tracks.find(t=>t.id===id)).filter(Boolean);
  tagPreviews = [];
  showToast('Buscando capas...');
  for (const t of selected) {
    const query = [t.artist, t.title].filter(Boolean).join(' ') || t.filename.replace(/\.[^.]+$/,'');
    try {
      const res = await fetch(`https://itunes.apple.com/search?term=${encodeURIComponent(query)}&entity=song&limit=1`);
      const data = await res.json();
      if (data.results?.length) tagPreviews.push({track: t, result: data.results[0], selected: true});
    } catch(e) {}
    await new Promise(r=>setTimeout(r,150));
  }
  if (tagPreviews.length) showTagPreviewModal(tagPreviews);
  else showToast('Nenhuma encontrada');
}

function showTagPreviewModal(previews) {
  const list = document.getElementById('tagPreviewList');
  const toggleBtn = document.getElementById('toggleAllBtn');

  if (previews[0]?.single) {
    const {track, results} = previews[0];
    document.getElementById('tagPreviewTitle').textContent = 'Resultados para: ' + (track.title || track.filename).slice(0,40);
    document.getElementById('tagPreviewSubtitle').textContent = 'Clique para selecionar qual aplicar';
    toggleBtn.style.display = 'none';
    list.innerHTML = results.map((r,i) => `
      <div class="tag-preview-item ${i===0?'selected':''}" onclick="selectSinglePreview(this,${i})" data-idx="${i}">
        <div class="tag-preview-cover">
          ${r.artworkUrl100
            ? `<img src="${r.artworkUrl100.replace('100x100bb','100x100bb')}" style="cursor:pointer">`
            : '🎵'}
        </div>
        <div class="tag-preview-info">
          <div class="tag-preview-title">${r.trackName || '—'}</div>
          <div class="tag-preview-sub">${r.artistName || '—'} · ${r.collectionName || '—'}</div>
        </div>
        <div class="tag-preview-check">
          <input type="radio" name="singleResult" value="${i}" ${i===0?'checked':''} onclick="event.stopPropagation();selectSinglePreview(this.closest('.tag-preview-item'),${i})">
        </div>
      </div>`).join('');
  } else {
    document.getElementById('tagPreviewTitle').textContent = previews.length + ' resultados encontrados';
    document.getElementById('tagPreviewSubtitle').textContent = 'Desmarque as que não quer atualizar';
    toggleBtn.style.display = 'inline-flex';
    list.innerHTML = previews.map((p,i) => `
      <div class="tag-preview-item checked-item" onclick="togglePreviewItem(this,${i})" data-idx="${i}">
        <div class="tag-preview-cover">
          ${p.result.artworkUrl100
            ? `<img src="${p.result.artworkUrl100.replace('100x100bb','100x100bb')}">`
            : '🎵'}
        </div>
        <div class="tag-preview-info">
          <div class="tag-preview-title">${p.result.trackName || '—'} <span style="color:var(--muted);font-weight:400">— ${p.result.artistName || '—'}</span></div>
          <div class="tag-preview-sub">↳ ${p.track.title || p.track.filename.slice(0,50)}</div>
        </div>
        <div class="tag-preview-check">
          <input type="checkbox" data-idx="${i}" checked onclick="event.stopPropagation();togglePreviewItem(this.closest('.tag-preview-item'),${i})">
        </div>
      </div>`).join('');
  }
  document.getElementById('tagPreviewModal').classList.add('open');
}

function selectSinglePreview(el, idx) {
  document.querySelectorAll('#tagPreviewList .tag-preview-item').forEach(item => {
    item.classList.remove('selected');
    item.querySelector('input[type=radio]').checked = false;
  });
  el.classList.add('selected');
  el.querySelector('input[type=radio]').checked = true;
}

function togglePreviewItem(el, idx) {
  const cb = el.querySelector('input[type=checkbox]');
  cb.checked = !cb.checked;
  el.classList.toggle('checked-item', cb.checked);
}

function toggleAllPreviews() {
  const cbs = document.querySelectorAll('#tagPreviewList input[type=checkbox]');
  const allChecked = [...cbs].every(c=>c.checked);
  cbs.forEach(c => c.checked = !allChecked);
}

function applyTagPreviews() {
  if (tagPreviews[0]?.single) {
    // Single: pega o radio selecionado
    const radio = document.querySelector('input[name=singleResult]:checked');
    if (!radio) { closeModal('tagPreviewModal'); return; }
    const r = tagPreviews[0].results[parseInt(radio.value)];
    const t = tagPreviews[0].track;
    t.title  = r.trackName  || t.title;
    t.artist = r.artistName || t.artist;
    t.album  = r.collectionName || t.album;
    t.cover  = r.artworkUrl100?.replace('100x100bb','300x300bb') || t.cover;
    dirty[t.id] = true;
    selectTrack(t.id); renderTracks();
    if (t.id === playingId) updatePlayerUI(t);
  } else {
    // Multiple: aplica os checkados
    const cbs = document.querySelectorAll('#tagPreviewList input[type=checkbox]:checked');
    let count = 0;
    cbs.forEach(cb => {
      const p = tagPreviews[parseInt(cb.dataset.idx)];
      if (!p) return;
      const r = p.result;
      const t = p.track;
      if (!t.title) t.title  = r.trackName;
      if (!t.artist) t.artist = r.artistName;
      if (!t.album) t.album  = r.collectionName;
      t.cover = r.artworkUrl100?.replace('100x100bb','300x300bb') || t.cover;
      dirty[t.id] = true;
      count++;
    });
    renderTracks();
    if (selectedId) selectTrack(selectedId);
    showToast(count + ' músicas atualizadas', 'success');
  }
  api('save-state','POST',{tracks,folders});
  closeModal('tagPreviewModal');
}

// ── FOLDERS CRUD ──────────────────────────────────────────────────────────────
function openNewFolderModal() {
  folderModalMode = 'create'; folderToRename = null;
  document.getElementById('folderModalTitle').textContent = 'Nova pasta';
  document.getElementById('folderModalBtn').textContent = 'Criar';
  document.getElementById('folderModalInput').value = '';
  document.getElementById('folderModal').classList.add('open');
  setTimeout(()=>document.getElementById('folderModalInput').focus(),100);
}

function openRenameFolder(folder) {
  folderModalMode = 'rename'; folderToRename = folder;
  document.getElementById('folderModalTitle').textContent = 'Renomear pasta';
  document.getElementById('folderModalBtn').textContent = 'Renomear';
  document.getElementById('folderModalInput').value = folder;
  document.getElementById('folderModal').classList.add('open');
  setTimeout(()=>document.getElementById('folderModalInput').focus(),100);
}

function confirmFolderModal() {
  const name = document.getElementById('folderModalInput').value.trim().toUpperCase();
  if (!name) { showToast('Nome inválido'); return; }
  if (folderModalMode === 'create') {
    if (folders.includes(name)) { showToast('Já existe'); return; }
    folders.push(name);
    showToast('Pasta "' + name + '" criada', 'success');
  } else {
    if (name === folderToRename) { closeModal('folderModal'); return; }
    if (folders.includes(name)) { showToast('Já existe'); return; }
    const idx = folders.indexOf(folderToRename);
    folders[idx] = name;
    tracks.forEach(t => { if (t.folder === folderToRename) { t.folder = name; dirty[t.id] = true; } });
    if (filterFolder === folderToRename) filterFolder = name;
    showToast('Renomeada para "' + name + '"', 'success');
  }
  renderFolders(); renderTracks();
  if (selectedId) selectTrack(selectedId);
  closeModal('folderModal');
  api('save-state','POST',{tracks,folders});
}

function openDeleteFolder(folder) {
  folderToDelete = folder;
  const count = tracks.filter(t=>t.folder===folder).length;
  document.getElementById('deleteFolderMsg').textContent = count > 0
    ? count + ' música(s) serão movidas para "Sem pasta".'
    : 'A pasta está vazia e será removida.';
  document.getElementById('deleteFolderModal').classList.add('open');
}

function confirmDeleteFolder() {
  if (!folderToDelete) return;
  tracks.forEach(t => { if (t.folder === folderToDelete) { t.folder = 'Sem pasta'; dirty[t.id] = true; } });
  folders = folders.filter(f => f !== folderToDelete);
  if (filterFolder === folderToDelete) filterFolder = 'Todas';
  folderToDelete = null;
  closeModal('deleteFolderModal');
  renderFolders(); renderTracks();
  if (selectedId) selectTrack(selectedId);
  api('save-state','POST',{tracks,folders});
  showToast('Pasta apagada', 'success');
}

document.getElementById('folderModalInput').addEventListener('keydown',e=>{if(e.key==='Enter')confirmFolderModal();});
document.getElementById('pastaInput').addEventListener('keydown',e=>{if(e.key==='Enter')confirmPasta();});

function closeModal(id) { document.getElementById(id).classList.remove('open'); }

// ── SAVE ──────────────────────────────────────────────────────────────────────
async function limparCapasRuins() {
  showToast('Analisando capas... pode demorar alguns minutos');
  try {
    const res = await api('clean-bad-covers', 'POST', {});
    if (res.ok) {
      const msg = res.removidos + ' capas ruins removidas' +
        (res.genericas ? ' (' + res.genericas + ' tipos genéricos)' : '');
      showToast(msg, 'success', 4000);
      // Recarrega para refletir mudanças
      setTimeout(() => recarregarPasta(), 1500);
    } else {
      showToast('Erro ao limpar capas');
    }
  } catch(e) {
    showToast('Erro: ' + e.message);
  }
}

function limparTags() {
  let count = 0;
  tracks.forEach(t => {
    const tOld = t.title, aOld = t.artist, albOld = t.album;
    t.title  = limparTexto(t.title);
    t.artist = limparTexto(t.artist);
    t.album  = limparTexto(t.album);
    if (t.title!==tOld || t.artist!==aOld || t.album!==albOld) { dirty[t.id]=true; count++; }
  });
  renderTracks();
  if (selectedId) selectTrack(selectedId);
  api('save-state','POST',{tracks,folders});
  showToast(count + ' tags limpas', 'success');
}

async function salvarTudo() {
  const alterados = tracks.filter(t => dirty[t.id]);
  if (!alterados.length) { showToast('Nenhuma alteração para salvar'); return; }
  const prog = document.getElementById('saveProgress');
  const fill = document.getElementById('saveFill');
  const cnt  = document.getElementById('saveProgressCount');
  document.getElementById('saveProgressText').textContent = 'Salvando...';
  prog.classList.add('active');
  let done = 0, erros = 0;
  for (const t of alterados) {
    try {
      // Envia capa: se base64 local converte para URL vazia (servidor baixa da URL)
      // se URL externa envia normalmente
      const payload = {
        id: t.id, path: t.path, filename: t.filename,
        title: t.title, artist: t.artist, album: t.album,
        folder: t.folder, dirty: true,
        // Se capa for base64 local, envia os bytes direto
        cover: t.cover || null,
        coverIsBase64: t.cover ? t.cover.startsWith('data:') : false
      };
      const res = await api('save-track', 'POST', payload);
      if (res.ok) {
        dirty[t.id] = false;
        // Atualiza path se arquivo foi movido
        if (res.path && res.path !== t.path) t.path = res.path;
      } else { erros++; }
    } catch(e) { erros++; }
    done++;
    fill.style.width = Math.round(done/alterados.length*100) + '%';
    cnt.textContent  = done + '/' + alterados.length;
    await new Promise(r => setTimeout(r, 30));
  }
  prog.classList.remove('active');
  renderFolders(); renderTracks(); updateStats();
  const msg = erros ? (done-erros) + ' salvas, ' + erros + ' erros' : done + ' músicas salvas!';
  showToast(msg, erros ? '' : 'success');
}

// ── PLAYER ────────────────────────────────────────────────────────────────────
function playTrack(id) {
  const t = tracks.find(x=>x.id===id);
  if (!t || !t.path) return;
  playingId = id;
  audio.src = '/audio?path=' + encodeURIComponent(t.path) + '&ts=' + Date.now();
  audio.load();
  audio.play().catch(e => showToast('Erro ao reproduzir'));
  document.getElementById('playPauseBtn').textContent = '⏸';
  updatePlayerUI(t); renderTracks();
}
function updatePlayerUI(t) {
  document.getElementById('playerTitle').textContent  = t.title  || t.filename;
  document.getElementById('playerArtist').textContent = t.artist || '—';
  document.getElementById('playerGenre').textContent  = t.folder || 'Sem pasta';
  const cover = document.getElementById('playerCover');
  cover.innerHTML = t.cover ? `<img src="${t.cover}">` : '🎵';
}
function togglePlay() {
  if (!audio.src) return;
  if (audio.paused) { audio.play(); document.getElementById('playPauseBtn').textContent = '⏸'; }
  else { audio.pause(); document.getElementById('playPauseBtn').textContent = '▶'; }
}
function nextTrack() { const v=getVisibleTracks(); const i=v.findIndex(t=>t.id===playingId); if(i<v.length-1)playTrack(v[i+1].id); else document.getElementById('playPauseBtn').textContent='▶'; }
function prevTrack() { if(audio.currentTime>3){audio.currentTime=0;return;} const v=getVisibleTracks(); const i=v.findIndex(t=>t.id===playingId); if(i>0)playTrack(v[i-1].id); }
function updateProgress() { if(!audio.duration)return; document.getElementById('progressFill').style.width=(audio.currentTime/audio.duration*100)+'%'; document.getElementById('currentTime').textContent=fmt(audio.currentTime); }
function updateDuration() { document.getElementById('totalTime').textContent=fmt(audio.duration); }
function seekTo(e) { if(!audio.duration)return; const b=document.getElementById('progressBar'); audio.currentTime=(e.offsetX/b.offsetWidth)*audio.duration; }
function setVolume(v) { audio.volume=v; }
function fmt(s) { if(!s||isNaN(s))return'0:00'; return Math.floor(s/60)+':'+Math.floor(s%60).toString().padStart(2,'0'); }

let toastTimeout;
function showToast(msg, type='', duration=2000) {
  const el=document.getElementById('toast'); el.textContent=msg; el.className='toast show '+type;
  clearTimeout(toastTimeout); toastTimeout=setTimeout(()=>el.classList.remove('show'),duration);
}

init();
</script>
</body>
</html>"""

# ── HANDLER ───────────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin','*')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        global pasta_atual
        path = self.path.split('?')[0]

        if path == '/':
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML.encode())

        elif path == '/api/state':
            state = carregar_estado()
            if state:
                self.send_json(state)
            else:
                musicas = listar_musicas(pasta_atual)
                pastas = listar_pastas(pasta_atual)
                pastas_default = ['Sem pasta'] + [p for p in pastas if p not in ['Sem pasta']]
                # Gera IDs únicos
                for i, m in enumerate(musicas):
                    m['id'] = 'tr_' + hashlib.md5(m['path'].encode()).hexdigest()[:8]
                data = {'tracks': musicas, 'folders': pastas_default, 'pasta': str(pasta_atual)}
                salvar_estado(data)
                self.send_json(data)

        elif path == '/api/scan':
            musicas = listar_musicas(pasta_atual)
            pastas = listar_pastas(pasta_atual)
            pastas_default = ['Sem pasta'] + [p for p in pastas if p not in ['Sem pasta']]
            for m in musicas:
                m['id'] = 'tr_' + hashlib.md5(m['path'].encode()).hexdigest()[:8]
            data = {'tracks': musicas, 'folders': pastas_default, 'pasta': str(pasta_atual)}
            salvar_estado(data)
            self.send_json(data)

        elif path.startswith('/audio'):
            qs = urllib.parse.parse_qs(self.path.split('?',1)[1] if '?' in self.path else '')
            fpath = qs.get('path',[''])[0]
            if fpath and Path(fpath).exists():
                fpath_obj = Path(fpath)
                ext = fpath_obj.suffix.lower()
                mime = {'mp3':'audio/mpeg','flac':'audio/flac','wav':'audio/wav','m4a':'audio/mp4','ogg':'audio/ogg','aac':'audio/aac'}.get(ext[1:],'audio/mpeg')
                size = fpath_obj.stat().st_size
                range_header = self.headers.get('Range','')
                if range_header:
                    # Suporte a Range requests (necessario para Safari/Chrome)
                    start, end = 0, size - 1
                    try:
                        rng = range_header.replace('bytes=','').split('-')
                        start = int(rng[0]) if rng[0] else 0
                        end   = int(rng[1]) if len(rng)>1 and rng[1] else size-1
                    except Exception:
                        pass
                    length = end - start + 1
                    self.send_response(206)
                    self.send_header('Content-Type', mime)
                    self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, size))
                    self.send_header('Content-Length', length)
                    self.send_header('Accept-Ranges', 'bytes')
                    self.end_headers()
                    with open(str(fpath), 'rb') as f:
                        f.seek(start)
                        self.wfile.write(f.read(length))
                else:
                    self.send_response(200)
                    self.send_header('Content-Type', mime)
                    self.send_header('Content-Length', size)
                    self.send_header('Accept-Ranges', 'bytes')
                    self.end_headers()
                    with open(str(fpath), 'rb') as f:
                        self.wfile.write(f.read())
            else:
                self.send_response(404); self.end_headers()
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        global pasta_atual
        length = int(self.headers.get('Content-Length',0))
        body = json.loads(self.rfile.read(length)) if length else {}
        path = self.path

        if path == '/api/set-pasta':
            p = Path(body.get('pasta',''))
            if p.exists() and p.is_dir():
                pasta_atual = p
                self.send_json({'ok': True})
            else:
                self.send_json({'ok': False})

        elif path == '/api/save-state':
            salvar_estado(body)
            self.send_json({'ok': True})

        elif path == '/api/delete-file':
            fpath = body.get('path','')
            try:
                p = Path(fpath)
                if p.exists() and p.is_file():
                    p.unlink()
                    self.send_json({'ok': True})
                else:
                    self.send_json({'ok': False, 'error': 'arquivo nao encontrado'})
            except Exception as e:
                self.send_json({'ok': False, 'error': str(e)})

        elif path == '/api/shazam':
            fpath = body.get('path', '')
            if not fpath or not Path(fpath).exists():
                self.send_json({'ok': False, 'error': 'arquivo não encontrado'})
                return
            result = shazam_recognize(fpath)
            if result:
                self.send_json({'ok': True, **result})
            else:
                self.send_json({'ok': False, 'error': 'não reconhecido'})

        elif path == '/api/clean-bad-covers':
            # Remove capas inválidas (muito pequenas ou hash repetido) dos arquivos
            import hashlib as hl
            MIN_SIZE = 5000  # 5KB mínimo
            removidos = 0
            erros = 0
            hashes_vistos = {}
            arquivos_limpar = []

            # Primeiro passa: coleta hashes de capas
            for f in pasta_atual.rglob('*'):
                if not (f.is_file() and f.suffix.lower() in EXTENSOES):
                    continue
                try:
                    ext = f.suffix.lower()
                    capa_data = None
                    if ext == '.mp3':
                        try:
                            tags = ID3(str(f))
                            for k in tags.keys():
                                if k.startswith('APIC'):
                                    capa_data = tags[k].data
                                    break
                        except: pass
                    elif ext == '.flac':
                        try:
                            audio = FLAC(str(f))
                            if audio.pictures:
                                capa_data = audio.pictures[0].data
                        except: pass

                    if capa_data:
                        if len(capa_data) < MIN_SIZE:
                            arquivos_limpar.append(f)
                        else:
                            h = hl.md5(capa_data).hexdigest()
                            if h not in hashes_vistos:
                                hashes_vistos[h] = {'count': 1, 'files': [f]}
                            else:
                                hashes_vistos[h]['count'] += 1
                                hashes_vistos[h]['files'].append(f)
                except: pass

            # Detecta hashes de capas muito repetidas (provável capa genérica)
            # Se a mesma capa aparece em mais de 50 músicas diferentes, é genérica
            capas_genericas = set()
            for h, info in hashes_vistos.items():
                if info['count'] > 50:
                    capas_genericas.add(h)
                    arquivos_limpar.extend(info['files'])

            # Remove capas dos arquivos identificados
            arquivos_limpar = list(set(arquivos_limpar))
            for f in arquivos_limpar:
                try:
                    ext = f.suffix.lower()
                    if ext == '.mp3':
                        try:
                            tags = ID3(str(f))
                            keys_apic = [k for k in tags.keys() if k.startswith('APIC')]
                            for k in keys_apic:
                                del tags[k]
                            tags.save(str(f))
                            removidos += 1
                        except: erros += 1
                    elif ext == '.flac':
                        try:
                            audio = FLAC(str(f))
                            audio.clear_pictures()
                            audio.save()
                            removidos += 1
                        except: erros += 1
                except: erros += 1

            self.send_json({'ok': True, 'removidos': removidos, 'erros': erros, 'genericas': len(capas_genericas)})

        elif path == '/api/save-track':
            t = body
            caminho = t.get('path','')
            is_dirty = t.get('dirty', True)
            if not caminho or not Path(caminho).exists():
                self.send_json({'ok': False, 'error': 'arquivo nao encontrado'})
                return
            ok = True
            if is_dirty:
                cover_val = t.get('cover','') or ''
                cover_url = None
                cover_data = None
                if cover_val.startswith('data:'):
                    # Capa base64 local (upload do usuario) - decodifica e embute
                    import base64 as b64mod
                    try:
                        header, b64data = cover_val.split(',', 1)
                        cover_data = b64mod.b64decode(b64data)
                    except Exception:
                        cover_data = None
                elif cover_val.startswith('http'):
                    cover_url = cover_val
                ok = aplicar_tags_com_dados(caminho, t.get('title',''), t.get('artist',''), t.get('album',''), cover_url, cover_data)
            # Move para pasta correta
            nova_pasta = t.get('folder','Sem pasta')
            caminho_atual = Path(caminho)
            if nova_pasta and nova_pasta not in ('Sem pasta',) and caminho_atual.parent.name != nova_pasta:
                novo_path = mover_arquivo(caminho, nova_pasta)
                caminho = novo_path
            self.send_json({'ok': ok, 'path': caminho})
        else:
            self.send_response(404); self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type')
        self.end_headers()

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import argparse, webbrowser
    parser = argparse.ArgumentParser()
    parser.add_argument('--pasta', default=str(PASTA_PADRAO))
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()

    pasta_atual = Path(args.pasta)
    if not pasta_atual.exists():
        print("Pasta nao encontrada: " + str(pasta_atual))
        sys.exit(1)

    server = HTTPServer(('localhost', args.port), Handler)
    url = 'http://localhost:' + str(args.port)
    print('Music Tagger rodando em: ' + url)
    print('Pasta: ' + str(pasta_atual))
    print('Pressione Ctrl+C para parar.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServidor parado.')
