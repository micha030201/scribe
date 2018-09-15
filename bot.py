import re
import sys
from base64 import b64encode
from contextlib import suppress
from itertools import count

import aiohttp
import discord


client = discord.Client()


def get_member(id):
    for member in client.get_all_members():
        if member.id == id:
            return member
    else:
        return client.get_user(id)


def get_role_name(id):
    for guild in client.guilds:
        for role in guild.roles:
            if role.id == id:
                return role.name
    else:
        return 'invalid-role'


md_tokens = '**', '*', '__', '_', '~~', ' ', '\n'


def weave(iterable, item):
    iterable = iter(iterable)
    yield next(iterable)
    for iterable_item in iterable:
        yield item
        yield iterable_item


def split_around(line, divider):
    if line in md_tokens:
        return [line]
    return weave(line.split(divider), divider)


def split_into_words_and_tokens(text):
    lines = [text]
    for token in md_tokens:
        lines = [
            (
                item
                .replace('&', '&amp;')
                .replace('&amp;amp;', '&amp;')
                .replace('<', '&lt;')
                .replace('&amp;lt;', '&lt;')
            )
            for line in lines
            for item in split_around(line, token)
        ]
    return filter(None, lines)


def wrap_text_and_render_markdown_lines(text, line_width=100):
    text += '\n'

    cache_clean = ''
    cache_dirty = ''

    _is_bold = False
    _is_italic = False
    _is_underline = False
    _is_strikethrough = False

    def open_bold():
        nonlocal cache_dirty, _is_bold
        assert not _is_bold
        _is_bold = True
        cache_dirty += '<tspan font-weight="bold">'

    def open_italic():
        nonlocal cache_dirty, _is_italic
        assert not _is_italic
        _is_italic = True
        cache_dirty += '<tspan font-style="italic">'

    def open_underline():
        nonlocal cache_dirty, _is_underline
        assert not _is_underline
        _is_underline = True
        cache_dirty += '<tspan font-decoration="underline">'

    def open_strikethrough():
        nonlocal cache_dirty, _is_strikethrough
        assert not _is_strikethrough
        _is_strikethrough = True
        cache_dirty += '<tspan font-decoration="line-through">'

    ###

    def close_bold():
        nonlocal _is_bold, cache_dirty
        assert _is_bold
        _is_bold = False
        cache_dirty += '</tspan>'

    def close_italic():
        nonlocal _is_italic, cache_dirty
        assert _is_italic
        _is_italic = False
        cache_dirty += '</tspan>'

    def close_underline():
        nonlocal _is_underline, cache_dirty
        assert _is_underline
        _is_underline = False
        cache_dirty += '</tspan>'

    def close_strikethrough():
        nonlocal _is_strikethrough, cache_dirty
        assert _is_strikethrough
        _is_strikethrough = False
        cache_dirty += '</tspan>'

    ###

    def append(word, color=None):
        nonlocal cache_clean, cache_dirty

        cache_clean += word
        if color is None:
            cache_dirty += word
        else:
            cache_dirty += f'<tspan fill="{color}">{word}</tspan> '

    ###

    def line_break():
        nonlocal cache_dirty, cache_clean

        cache_dirty = cache_dirty.replace('> ', '>')

        todo = []

        with suppress(AssertionError):
            close_bold()
            todo.append(open_bold)
        with suppress(AssertionError):
            close_italic()
            todo.append(open_italic)
        with suppress(AssertionError):
            close_underline()
            todo.append(open_underline)
        with suppress(AssertionError):
            close_strikethrough()
            todo.append(open_strikethrough)

        yield cache_dirty
        cache_clean = cache_dirty = ''

        for func in todo:
            func()

    def transform_token(word):
        if word == '**':
            try:
                close_bold()
            except AssertionError:
                open_bold()
        elif word in ('*', '_'):
            try:
                close_italic()
            except AssertionError:
                open_italic()
        elif word == '__':
            try:
                close_underline()
            except AssertionError:
                open_underline()
        elif word == '~~':
            try:
                close_strikethrough()
            except AssertionError:
                open_strikethrough()
        else:
            match = re.match('&lt;(.*?)([0-9]+)>', word)
            if match:
                id = int(match.group(2))
                if match.group(1) in ('@', '@!'):
                    append('@' + get_member(id).display_name, '#0096cf')
                elif match.group(1) == '#':
                    append('#' + client.get_channel(id).name, '#0096cf')
                elif match.group(1) == '@&amp;':
                    append('@' + get_role_name(id), '#0096cf')
                else:
                    # custom emoji
                    append(match.group(1))
            else:
                append(word, '#0096cf' if word.startswith('http') else None)

    for word in split_into_words_and_tokens(text):
        if word == '\n':
            yield from line_break()
        elif len(cache_clean) + len(word) > line_width and len(cache_clean) > 1:
            yield from line_break()
            transform_token(word)
        else:
            transform_token(word)


###

async def download_bytes(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.read()


async def get_picture(url, _cache={}):
    try:
        return _cache[url]
    except KeyError:
        picture = b64encode(await download_bytes(url)).decode('ascii')
        _cache[url] = picture
        return picture


async def transcribe_message(message):
    buf = []
    def w(line):
        buf.append(line + '\n')

    w('<rect x="0" y="0" height="8000" width="800" fill="#36393f"/>')

    avatar = await get_picture(message.author.avatar_url_as(static_format='png', size=64))

    try:
        role_colour = message.author.colour
    except AttributeError:
        role_colour = 'white'
    else:
        if role_colour.value == 0:
            role_colour = 'white'
        else:
            role_colour = str(role_colour)

    w(f'''
    <defs>
      <pattern id="avatar" x="32" y="10" patternUnits="userSpaceOnUse" height="64" width="64">
        <image x="0" y="0" height="64" width="64" xlink:href="data:image/png;base64,{avatar}"></image>
      </pattern>
    </defs>
    <circle cx="64" cy="42" r="32" fill="url(#avatar)"/>
    ''')

    w(f'''
    <text x="128" y="25" font-family="sans-serif">
      <tspan font-size="15px" font-weight="bold" fill="{role_colour}">{message.author.display_name}</tspan>
      <tspan font-size="10px" fill="white" fill-opacity="0.8">{message.created_at.strftime('%b %-d, %Y %H:%M')}</tspan>
    </text>
    ''')

    w(f'<text x="128" y="35" font-family="sans-serif" fill="white">')
    lines = list(wrap_text_and_render_markdown_lines(message.content, 65))
    for line in lines:
        if line == '':
            line = '<tspan fill="#36393f">---</tspan>'
        w(f'<tspan font-size="15px" x="128" dy="20">{line}</tspan>')
    w('</text>')

    y_offset = len(lines) * 20 + 50

    for reaction, offset in zip(message.reactions, count(0, 50)):
        w(f'<rect x="{128 + offset}" y="{y_offset}" width="40" height="20" rx="5" ry="5" fill="white" fill-opacity="0.2" />')
        w(f'<text x="{132 + offset}" y="{14 + y_offset}" font-family="sans-serif" font-size="12px" fill="white">{reaction.count}</text>')
        if type(reaction.emoji) is str:
            w(f'<text x="{149 + offset}" y="{15 + y_offset}" font-size="13">{reaction.emoji}</text>')
        else:
            pic = await get_picture(reaction.emoji.url)
            w(f'<image x="{149 + offset}" y="{2.5 + y_offset}" xlink:href="data:image/png;base64,{pic}" width="15" height="15" />')


    buf.insert(0, f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="700" height="{y_offset + 30}" viewBox="0 0 700 {y_offset + 30}">')


    w('</svg>')

    return ''.join(buf)


async def my_background_task():
    await client.wait_until_ready()
    channel = client.get_channel(int(sys.argv[2]))
    assert channel is not None
    async for message in channel.history(limit=None):
        filename = f'{str(message.created_at.timestamp()).replace(".", ""):0<20}.svg'
        svg_text = await transcribe_message(message)

        with open(filename, 'w') as f:
            f.write(svg_text)
        print(filename)

        #await asyncio.sleep(1)
    print('\nDone!')


@client.event
async def on_ready():
    print('Logged in as')
    print(client.user.name)
    print(client.user.id)
    print('------')


if __name__ == '__main__':
    client.loop.create_task(my_background_task())
    client.run(sys.argv[1])
