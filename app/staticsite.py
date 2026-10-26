"""Página estática (somente leitura) com os concursos abertos, para publicar no GitHub Pages."""

import html
from datetime import datetime

from . import clock, config
from . import repository as repo

STATUS = {
    'open': ('Inscrições abertas', 'ok'),
    'upcoming': ('Em breve', 'ok'),
    'verify': ('A conferir', 'warn'),
    'announced': ('Anunciado', 'warn'),
    'suspended': ('Suspenso', 'bad'),
    'cancelled': ('Cancelado', 'bad'),
    'closed': ('Encerrado', 'bad'),
}


def esc(value):
    return html.escape(str(value or ''), quote=True)


def br_date(iso):
    return '/'.join(reversed(iso.split('-'))) if iso else 'A confirmar'


def money(item):
    low, high = item.get('salary_min'), item.get('salary_max')
    if not (item.get('salary_verified') and (low or high)):
        return 'A confirmar'

    def fmt(v):
        return 'R$ ' + f'{v:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')

    return fmt(low) if low == high or not high else f'{fmt(low)} a {fmt(high)}'


def card(item):
    label, tone = STATUS.get(item['status'], ('A conferir', 'warn'))
    badges = [f'<span class="b {tone}">{label}</span>']
    badges.append(
        '<span class="b ok">Edital validado</span>'
        if item.get('document_verified')
        else '<span class="b mute">Sem prova documental</span>'
    )
    if item.get('type') == 'pss':
        badges.append('<span class="b temp">Temporário (PSS)</span>')
    links = []
    if item.get('notice_url'):
        links.append(f'<a href="{esc(item["notice_url"])}" rel="noopener">Edital</a>')
    if item.get('official_url') and item['official_url'] != item.get('notice_url'):
        links.append(f'<a href="{esc(item["official_url"])}" rel="noopener">Site oficial</a>')
    period = (
        f'{br_date(item.get("registration_start"))} a {br_date(item.get("registration_end"))}'
        if item.get('registration_end')
        else 'A confirmar'
    )
    search = esc(' '.join(str(item.get(k) or '') for k in ('title', 'agency', 'position', 'state')).lower())
    return (
        f'<article class="card" data-s="{search}" data-uf="{esc(item.get("state"))}" data-t="{esc(item.get("type"))}">'
        f'<div class="badges">{"".join(badges)}</div>'
        f'<h2>{esc(item["title"])}</h2>'
        f'<p class="sub">{esc(item.get("agency") or item.get("source"))} · {esc(item.get("position") or "cargo a conferir")}</p>'
        f'<dl><div><dt>Salário</dt><dd>{money(item)}</dd></div>'
        f'<div><dt>Inscrições</dt><dd>{period}</dd></div>'
        f'<div><dt>Prova</dt><dd>{br_date(item.get("exam_date"))}</dd></div></dl>'
        f'<p class="links">{" · ".join(links)}</p></article>'
    )


def build():
    items = [i for i in repo.query_opportunities(include_dismissed=False) if i['status'] != 'closed']
    health = repo.source_health()
    problems = sum(1 for h in health if h.get('error'))
    now = datetime.now(clock.TZ).strftime('%d/%m/%Y %H:%M')
    name = esc(config.app_name())
    cards = ''.join(card(i) for i in items) or '<p class="empty">Nenhum concurso de engenharia aberto no momento.</p>'
    return PAGE.format(
        name=name,
        when=now,
        count=len(items),
        word='concurso' if len(items) == 1 else 'concursos',
        problems=problems,
        cards=cards,
    )


PAGE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name}</title>
<style>
:root{{--bg:#f6f7f9;--fg:#15202b;--card:#fff;--mute:#5b6b7b;--line:#dde3ea;--ok:#0f7b45;--warn:#9a6a00;--bad:#a33;--link:#1558d6}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1220;--fg:#e7edf5;--card:#121b2d;--mute:#9bacc0;--line:#24324a;--ok:#4fd18b;--warn:#f0c14b;--bad:#ff8585;--link:#7fb0ff}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,sans-serif}}
main{{max-width:820px;margin:0 auto;padding:20px 16px 48px}}h1{{margin:.2em 0}}
.meta{{color:var(--mute);font-size:.9rem}}input{{width:100%;margin:14px 0;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--fg);font:inherit}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin:12px 0}}
.card h2{{font-size:1.05rem;margin:.5em 0 .1em}}.sub{{margin:0;color:var(--mute)}}
.badges{{display:flex;gap:6px;flex-wrap:wrap}}.b{{font-size:.75rem;font-weight:600;padding:2px 9px;border-radius:99px;border:1px solid var(--line)}}
.ok{{color:var(--ok)}}.warn{{color:var(--warn)}}.bad{{color:var(--bad)}}.mute{{color:var(--mute)}}.temp{{color:var(--link)}}
dl{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:12px 0}}dt{{font-size:.75rem;color:var(--mute)}}dd{{margin:0;font-weight:600}}
a{{color:var(--link)}}.links{{margin:.3em 0 0}}.empty{{color:var(--mute)}}
</style></head><body><main>
<h1>{name}</h1>
<p class="meta">Atualizado em {when} (Brasília) · {count} {word} · {problems} fontes com problema. Só fontes oficiais; confira sempre o edital.</p>
<input id="q" type="search" placeholder="Filtrar por cidade, estado ou cargo" aria-label="Filtrar">
<div id="list">{cards}</div>
<script>
var q=document.getElementById('q');q.addEventListener('input',function(){{var t=q.value.toLowerCase();
document.querySelectorAll('.card').forEach(function(c){{c.style.display=c.dataset.s.indexOf(t)>-1?'':'none'}})}});
</script></main></body></html>
"""
