"""
Simple Pygame Chatbot UI
- Type a question in the input box and press Enter to send.
- If OPENAI_API_KEY environment variable is set, it will call the OpenAI ChatCompletion API (requires openai package).
- If no API key is present or openai isn't installed, a local fallback responder handles simple questions.

Note: Calling OpenAI from within this environment may not be possible; this script is ready to run on your machine.
"""

import os
import pygame
import threading
import time
import queue
import webbrowser
import urllib.request
import io
import json
import re

try:
    import openai
except Exception:
    openai = None

# tts
try:
    import pyttsx3
except Exception:
    pyttsx3 = None

from pathlib import Path

ASSET_DIR = Path(r"C:\Users\slane\Downloads")
WIDTH, HEIGHT = 800, 600
FPS = 60

# Colors
BG = (30, 30, 30)
PANEL = (40, 40, 40)
TEXT = (230, 230, 230)
INPUT_BG = (25, 25, 25)

# Thread-safe queue for chat results
result_q = queue.Queue()

# Simple fallback responder
def local_responder(prompt):
    p = prompt.lower().strip()
    # image query prefix: "image: cats" or "/img cats"
    if p.startswith('image:') or p.startswith('/img'):
        # return a special directive for the worker to handle
        return {'_image_query': prompt.split(':',1)[1].strip() if ':' in prompt else prompt.split(' ',1)[1] if ' ' in prompt else ''}
    if 'weather' in p:
        return "I don't have live weather here, but remember to bring a jacket if it's cold!"
    if 'time' in p:
        return f"Local time is {time.asctime()}"
    if 'hello' in p or 'hi' in p:
        return "Hello! How can I help you today?"
    if 'help' in p:
        return "This is a demo chatbot. You can ask simple questions or set OPENAI_API_KEY to use OpenAI." 
    return "Sorry, I can't answer that locally. Try setting an OpenAI API key in your environment to get full answers."

# OpenAI call wrapper
def call_openai(prompt, api_key=None):
    if openai is None:
        return "OpenAI package not installed. Install `openai` to enable full responses."
    if api_key is None:
        return "OpenAI API key not set in environment variable OPENAI_API_KEY."
    try:
        openai.api_key = api_key
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            temperature=0.6,
            max_tokens=400,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"OpenAI request failed: {e}"


def google_cse_image_search(query, api_key, cx):
    # Uses Google Custom Search JSON API to find images. Requires API key and search engine cx set to image search.
    try:
        qs = urllib.parse.urlencode({
            'q': query,
            'cx': cx,
            'key': api_key,
            'searchType': 'image',
            'num': 1,
        })
        url = f'https://www.googleapis.com/customsearch/v1?{qs}'
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.load(resp)
        items = data.get('items')
        if items and len(items) > 0:
            return items[0].get('link')
    except Exception as e:
        return None
    return None

# background thread function to process queries
def worker_thread(prompt, use_openai):
    api_key = os.getenv('OPENAI_API_KEY') if use_openai else None
    # check for image query directive from local_responder
    local = local_responder(prompt)
    if isinstance(local, dict) and '_image_query' in local:
        q = local['_image_query']
        # attempt Google CSE if credentials present
        gkey = os.getenv('GOOGLE_API_KEY')
        gcx = os.getenv('GOOGLE_CX')
        if gkey and gcx:
            link = google_cse_image_search(q, gkey, gcx)
            if link:
                # download image bytes
                try:
                    with urllib.request.urlopen(link, timeout=10) as resp:
                        data = resp.read()
                    # save to temp file
                    fname = ASSET_DIR / f"img_search_{int(time.time())}.png"
                    with open(fname, 'wb') as f:
                        f.write(data)
                    result_q.put({'text': f'Found image for "{q}"', 'image': str(fname)})
                    return
                except Exception as e:
                    # fallback to opening browser
                    webbrowser.open(f'https://www.google.com/search?tbm=isch&q={urllib.parse.quote(q)}')
                    result_q.put(f'Opened browser for images: {q}')
                    return
        else:
            # no API keys: just open browser to Google Images
            webbrowser.open(f'https://www.google.com/search?tbm=isch&q={urllib.parse.quote(q)}')
            result_q.put(f'Opened browser for images: {q}')
            return

    # regular text response path
    if use_openai and api_key and openai is not None:
        res = call_openai(prompt, api_key=api_key)
    else:
        res = local if isinstance(local, str) else local_responder(prompt)
    result_q.put(res)


def init_tts():
    if pyttsx3 is None:
        return None
    try:
        engine = pyttsx3.init()
        engine.setProperty('rate', 170)
        return engine
    except Exception:
        return None

def speak_text(engine, text):
    if engine is None:
        return
    try:
        engine.say(text)
        engine.runAndWait()
    except Exception:
        pass


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption('Pygame Chatbot')
    clock = pygame.time.Clock()
    tts_engine = init_tts()

    font = pygame.font.SysFont(None, 22)
    big = pygame.font.SysFont(None, 28)
    mono = pygame.font.SysFont('Consolas', 18)

    # try to load background image 'chatjam.png' from assets
    chat_bg = None
    try:
        bg_path = ASSET_DIR / 'chatjam.png'
        if bg_path.exists():
            _img = pygame.image.load(str(bg_path)).convert()
            chat_bg = pygame.transform.smoothscale(_img, (WIDTH, HEIGHT))
    except Exception:
        chat_bg = None

    input_text = ''
    chat = []  # list of (speaker, text)
    # initial greeting from ChatJam
    chat.append(('Bot', "hello i'm chatjam how can i help you today"))

    input_active = True
    use_openai = (os.getenv('OPENAI_API_KEY') is not None and openai is not None)
    ai_toggle_rect = None
    signed_in = False
    sign_rect = None
    image_modal = None

    # items rendered this frame that can be clicked: dicts with keys: rect, type, url/image
    rendered_items = []

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                mx, my = ev.pos
                # close image modal if open
                if image_modal:
                    image_modal = None
                    continue
                # check sign up click
                if sign_rect and sign_rect.collidepoint((mx, my)):
                    webbrowser.open('https://accounts.google.com/')
                    signed_in = True
                    continue
                # check other clickable items
                for itm in rendered_items:
                    try:
                        if itm['rect'].collidepoint((mx, my)):
                            if itm['type'] == 'link':
                                webbrowser.open(itm.get('url'))
                            elif itm['type'] == 'image':
                                image_modal = itm.get('image')
                            break
                    except Exception:
                        pass
            elif ev.type == pygame.KEYDOWN and input_active:
                if ev.key == pygame.K_BACKSPACE:
                    input_text = input_text[:-1]
                elif ev.key == pygame.K_RETURN:
                    if input_text.strip():
                        chat.append(('You', input_text))
                        # start worker thread
                        t = threading.Thread(target=worker_thread, args=(input_text, use_openai), daemon=True)
                        t.start()
                        input_text = ''
                else:
                    # basic printable
                    if ev.unicode:
                        input_text += ev.unicode
                # toggle OpenAI with Shift key
                if ev.key in (pygame.K_LSHIFT, pygame.K_RSHIFT):
                    use_openai = not use_openai
                    # notify user in chat
                    if use_openai and (openai is None or os.getenv('OPENAI_API_KEY') is None):
                        chat.append(('Bot', 'OpenAI enabled but not configured: install openai package and set OPENAI_API_KEY to use it.'))
                    else:
                        chat.append(('Bot', f'OpenAI usage set to {use_openai}'))

        # collect results
        try:
            while True:
                res = result_q.get_nowait()
                # if image result dict
                if isinstance(res, dict) and 'image' in res:
                    chat.append(('Bot', res))
                    # also speak short text
                    if 'text' in res and tts_engine:
                        threading.Thread(target=speak_text, args=(tts_engine, res['text']), daemon=True).start()
                else:
                    chat.append(('Bot', res))
                    if tts_engine and isinstance(res, str):
                        threading.Thread(target=speak_text, args=(tts_engine, res), daemon=True).start()
        except queue.Empty:
            pass

        # draw (background image if available)
        if chat_bg:
            screen.blit(chat_bg, (0, 0))
        else:
            screen.fill(BG)
        # chat panel
        panel_rect = pygame.Rect(12,12, WIDTH-24, HEIGHT-120)
        pygame.draw.rect(screen, PANEL, panel_rect, border_radius=8)

        # render chat from bottom up
        y = panel_rect.bottom - 12
        rendered_items.clear()
        for speaker, text in reversed(chat[-40:]):
            # speaker label
            lab = big.render(f"{speaker}:", True, (200,200,200))
            y -= lab.get_height() + 6
            screen.blit(lab, (panel_rect.left + 16, y))
            y -= 6

            if isinstance(text, dict) and 'image' in text:
                # draw image and make it clickable
                try:
                    img = pygame.image.load(text['image']).convert_alpha()
                    max_w = panel_rect.width - 40
                    if img.get_width() > max_w:
                        scale = max_w / img.get_width()
                        img = pygame.transform.smoothscale(img, (int(img.get_width()*scale), int(img.get_height()*scale)))
                    y -= img.get_height()
                    rect = img.get_rect(topleft=(panel_rect.left + 16, y))
                    screen.blit(img, rect.topleft)
                    rendered_items.append({'rect': rect, 'type': 'image', 'image': text['image']})
                    y -= 12
                except Exception:
                    # fallback to showing text
                    txts = font.render(str(text.get('text','[image]')), True, TEXT)
                    y -= txts.get_height() + 6
                    screen.blit(txts, (panel_rect.left + 16, y))
            else:
                # support code blocks fenced by ``` and links (http...)
                s = text if isinstance(text, str) else str(text)
                # split into code blocks
                parts = re.split(r'(```[\s\S]*?```)', s)
                for part in parts:
                    if part.startswith('```') and part.endswith('```'):
                        code = part.strip('`')
                        # render in monospace
                        for line in code.splitlines()[::-1]:
                            txts = mono.render(line, True, (200,220,200))
                            y -= txts.get_height() + 4
                            screen.blit(txts, (panel_rect.left + 24, y))
                    else:
                        # detect links
                        words = part.split(' ')
                        line = ''
                        for w in words:
                            test = (line + ' ' + w).strip()
                            surf = font.render(test, True, TEXT)
                            if surf.get_width() > panel_rect.width - 40 and line:
                                # draw current line
                                txts = font.render(line, True, TEXT)
                                y -= txts.get_height() + 6
                                screen.blit(txts, (panel_rect.left + 16, y))
                                line = w
                            else:
                                line = test
                        if line:
                            # render links inside the line
                            # find urls
                            url_regex = r'(https?://[^\s]+)'
                            last_x = panel_rect.left + 16
                            # render in segments
                            for m in re.finditer(url_regex, line):
                                pre = line[:m.start()]
                                url = m.group(1)
                                pre_surf = font.render(pre, True, TEXT)
                                y -= pre_surf.get_height() + 6
                                screen.blit(pre_surf, (panel_rect.left + 16, y))
                                url_surf = font.render(url, True, (100,180,240))
                                rect = url_surf.get_rect(topleft=(panel_rect.left + 16 + pre_surf.get_width(), y))
                                screen.blit(url_surf, rect.topleft)
                                rendered_items.append({'rect': rect, 'type': 'link', 'url': url})
                                # rest after url
                                rest = line[m.end():]
                                if rest.strip():
                                    rest_surf = font.render(rest, True, TEXT)
                                    screen.blit(rest_surf, (rect.right, y))
                            else:
                                # no url match, just render line
                                txts = font.render(line, True, TEXT)
                                y -= txts.get_height() + 6
                                screen.blit(txts, (panel_rect.left + 16, y))
            if y < panel_rect.top + 10:
                break

        # input box
        inp_rect = pygame.Rect(12, HEIGHT-96, WIDTH-24, 72)
        pygame.draw.rect(screen, INPUT_BG, inp_rect, border_radius=8)
        # render input text
        txt = font.render(input_text, True, TEXT)
        screen.blit(txt, (inp_rect.left + 12, inp_rect.top + 12))

        # hint
        hint = font.render('Press Enter to send. OpenAI enabled: ' + str(use_openai), True, (180,180,180))
        screen.blit(hint, (inp_rect.left + 12, inp_rect.bottom - 24))

        # AI toggle badge (top-right)
        badge_text = 'AI: ON' if use_openai else 'AI: OFF'
        badge_col = (30,180,30) if use_openai else (180,30,30)
        badge_surf = font.render(badge_text, True, (255,255,255))
        ai_toggle_rect = badge_surf.get_rect(topright=(WIDTH-12, 12))
        pygame.draw.rect(screen, badge_col, ai_toggle_rect.inflate(8,6), border_radius=6)
        screen.blit(badge_surf, ai_toggle_rect)

        pygame.display.flip()

    pygame.quit()

if __name__ == '__main__':
    main()
