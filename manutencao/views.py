from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.http import HttpResponse
from .models import Equipamento, Manutencao, Oficina

# PDF
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import io
import calendar
import os


# ── Views principais ──────────────────────────────────────────────────────────

@login_required
def dashboard(request):
    equipamentos = Equipamento.objects.all()
    manutencoes  = Manutencao.objects.select_related("equipamento").all()

    # Dados gráfico pizza — dias parados por equipamento
    dados_pizza = {}
    for m in manutencoes.filter(status="concluida"):
        if m.dias_ate_conclusao and m.dias_ate_conclusao > 0:
            nome = m.equipamento.nome
            dados_pizza[nome] = dados_pizza.get(nome, 0) + m.dias_ate_conclusao

    # Dados gráfico linha — número de manutenções por mês (últimos 12 meses)
    from django.db.models.functions import TruncMonth
    from django.db.models import Count
    import json

    por_mes = (
        Manutencao.objects
        .annotate(mes=TruncMonth("data_registro"))
        .values("mes")
        .annotate(total=Count("id"))
        .order_by("mes")
    )

    MESES_PT = {
        1:"Jan", 2:"Fev", 3:"Mar", 4:"Abr",
        5:"Mai", 6:"Jun", 7:"Jul", 8:"Ago",
        9:"Set", 10:"Out", 11:"Nov", 12:"Dez"
    }

    linha_labels = [f"{MESES_PT[p['mes'].month]}/{p['mes'].year}" for p in por_mes]
    linha_dados  = [p["total"] for p in por_mes]

    context = {
        "total_equipamentos":   equipamentos.count(),
        "aguardando_orcamento": manutencoes.filter(status="aguardando_orcamento").count(),
        "orcamento_aprovado":   manutencoes.filter(status="orcamento_aprovado").count(),
        "concluidas":           manutencoes.filter(status="concluida").count(),
        "proximas":             manutencoes.filter(status="aguardando_orcamento").order_by("data_prevista")[:5],
        "pizza_labels":         list(dados_pizza.keys()),
        "pizza_dados":          list(dados_pizza.values()),
        "linha_labels":         linha_labels,
        "linha_dados":          linha_dados,
    }
    return render(request, "manutencao/dashboard.html", context)


@login_required
def lista_manutencoes(request):
    from django.core.paginator import Paginator

    manutencoes = Manutencao.objects.select_related("equipamento").all()

    status = request.GET.get("status")
    eq_id  = request.GET.get("equipamento")
    mes    = request.GET.get("mes")
    ano    = request.GET.get("ano")
    of_id  = request.GET.get("oficina")

    if status:
        manutencoes = manutencoes.filter(status=status)
    if eq_id:
        manutencoes = manutencoes.filter(equipamento_id=eq_id)
    if mes:
        manutencoes = manutencoes.filter(data_registro__month=mes)
    if ano:
        manutencoes = manutencoes.filter(data_registro__year=ano)
    if of_id:
        manutencoes = manutencoes.filter(oficina_id=of_id)

    from django.db.models.functions import ExtractYear
    anos_disponiveis = (
        Manutencao.objects.annotate(ano=ExtractYear("data_registro"))
        .values_list("ano", flat=True)
        .distinct()
        .order_by("-ano")
    )

    paginator   = Paginator(manutencoes, 7)
    pagina_num  = request.GET.get("pagina", 1)
    pagina      = paginator.get_page(pagina_num)

    # Monta query string sem o parâmetro pagina para usar nos links
    query = request.GET.copy()
    query.pop("pagina", None)
    query_string = query.urlencode()

    context = {
        "manutencoes":      pagina,
        "pagina":           pagina,
        "query_string":     query_string,
        "equipamentos":     Equipamento.objects.all(),
        "oficinas":         Oficina.objects.all(),
        "filtro_status":    status,
        "filtro_eq":        eq_id,
        "filtro_mes":       mes,
        "filtro_ano":       ano,
        "filtro_oficina":   of_id,
        "anos_disponiveis": anos_disponiveis,
    }
    return render(request, "manutencao/lista_manutencoes.html", context)


@login_required
def cadastrar_manutencao(request):
    if request.method == "POST":
        Manutencao.objects.create(
            equipamento_id=request.POST["equipamento"],
            tipo          =request.POST["tipo"],
            descricao     =request.POST["descricao"],
            data_registro =request.POST["data_registro"],
            data_prevista =request.POST["data_prevista"],
            responsavel   =request.POST.get("responsavel", ""),
            horimetro     =request.POST.get("horimetro") or None,
            oficina_id    =request.POST.get("oficina") or None,
            status        ="aguardando_orcamento",
            criado_por    =request.user,
        )
        return redirect("lista_manutencoes")

    return render(request, "manutencao/cadastrar_manutencao.html", {
        "equipamentos": Equipamento.objects.all(),
        "oficinas":     Oficina.objects.all(),
        "today":        timezone.now().date().strftime("%Y-%m-%d"),
    })


@login_required
def concluir_manutencao(request, pk):
    m = get_object_or_404(Manutencao, pk=pk)
    m.status         = "concluida"
    m.data_realizada = timezone.now().date()
    m.save()
    return redirect("lista_manutencoes")


@login_required
def cadastrar_equipamento(request):
    if request.method == "POST":
        Equipamento.objects.create(
            nome       =request.POST["nome"],
            localizacao=request.POST["localizacao"],
            descricao  =request.POST.get("descricao", ""),
            criado_por =request.user,
        )
        return redirect("lista_equipamentos")
    return render(request, "manutencao/cadastrar_equipamento.html")


# ── Exportar PDF ──────────────────────────────────────────────────────────────

@login_required
def editar_manutencao(request, pk):
    m = get_object_or_404(Manutencao, pk=pk)

    # Regra 1 — registro concluído não pode ser editado por ninguém
    if m.status == "concluida":
        return render(request, "manutencao/sem_permissao.html", {
            "motivo": "Este registro já foi concluído e não pode mais ser editado."
        })

    # Regra 2 — somente o criador pode editar
    if m.criado_por != request.user:
        return render(request, "manutencao/sem_permissao.html", {
            "motivo": "Somente o usuário que criou este registro pode editá-lo."
        })

    if request.method == "POST":
        m.equipamento_id = request.POST["equipamento"]
        m.tipo           = request.POST["tipo"]
        m.descricao      = request.POST["descricao"]
        m.data_registro  = request.POST["data_registro"]
        m.data_prevista  = request.POST["data_prevista"]
        m.responsavel    = request.POST.get("responsavel", "")
        m.horimetro      = request.POST.get("horimetro") or None
        m.oficina_id     = request.POST.get("oficina") or None
        m.status         = request.POST["status"]
        if m.status == "concluida" and not m.data_realizada:
            m.data_realizada = timezone.now().date()
        m.save()
        return redirect("lista_manutencoes")

    context = {
        "m":            m,
        "equipamentos": Equipamento.objects.all(),
        "oficinas":     Oficina.objects.all(),
    }
    return render(request, "manutencao/editar_manutencao.html", context)


@login_required
def editar_equipamento(request, pk):
    eq = get_object_or_404(Equipamento, pk=pk)
    if eq.criado_por != request.user:
        return render(request, "manutencao/sem_permissao.html", {
            "motivo": "Somente o usuário que cadastrou este equipamento pode editá-lo."
        })
    if request.method == "POST":
        eq.nome        = request.POST["nome"]
        eq.localizacao = request.POST["localizacao"]
        eq.descricao   = request.POST.get("descricao", "")
        eq.save()
        return redirect("lista_equipamentos")
    return render(request, "manutencao/editar_equipamento.html", {"eq": eq})


@login_required
def excluir_equipamento(request, pk):
    eq = get_object_or_404(Equipamento, pk=pk)
    if eq.criado_por != request.user:
        return render(request, "manutencao/sem_permissao.html", {
            "motivo": "Somente o usuário que cadastrou este equipamento pode excluí-lo."
        })
    if request.method == "POST":
        eq.delete()
        return redirect("lista_equipamentos")
    return render(request, "manutencao/confirmar_exclusao.html", {
        "objeto": eq.nome, "voltar": "lista_equipamentos"
    })


@login_required
def lista_equipamentos(request):
    equipamentos = Equipamento.objects.all()
    return render(request, "manutencao/lista_equipamentos.html", {"equipamentos": equipamentos})


@login_required
def lista_oficinas(request):
    oficinas = Oficina.objects.all()
    return render(request, "manutencao/lista_oficinas.html", {"oficinas": oficinas})


@login_required
def cadastrar_oficina(request):
    if request.method == "POST":
        Oficina.objects.create(
            nome       =request.POST["nome"],
            telefone   =request.POST.get("telefone", ""),
            responsavel=request.POST.get("responsavel", ""),
            criado_por =request.user,
        )
        return redirect("lista_oficinas")
    return render(request, "manutencao/cadastrar_oficina.html")


@login_required
def editar_oficina(request, pk):
    of = get_object_or_404(Oficina, pk=pk)
    if of.criado_por != request.user:
        return render(request, "manutencao/sem_permissao.html", {
            "motivo": "Somente o usuário que cadastrou esta oficina pode editá-la."
        })
    if request.method == "POST":
        of.nome        = request.POST["nome"]
        of.telefone    = request.POST.get("telefone", "")
        of.responsavel = request.POST.get("responsavel", "")
        of.save()
        return redirect("lista_oficinas")
    return render(request, "manutencao/editar_oficina.html", {"of": of})


@login_required
def excluir_oficina(request, pk):
    of = get_object_or_404(Oficina, pk=pk)
    if of.criado_por != request.user:
        return render(request, "manutencao/sem_permissao.html", {
            "motivo": "Somente o usuário que cadastrou esta oficina pode excluí-la."
        })
    if request.method == "POST":
        of.delete()
        return redirect("lista_oficinas")
    return render(request, "manutencao/confirmar_exclusao.html", {
        "objeto": of.nome, "voltar": "lista_oficinas"
    })


@login_required
def exportar_pdf(request):
    manutencoes = Manutencao.objects.select_related("equipamento", "oficina").all()
    status = request.GET.get("status")
    mes    = request.GET.get("mes")
    ano    = request.GET.get("ano")
    of_id  = request.GET.get("oficina")

    if status:
        manutencoes = manutencoes.filter(status=status)
    if mes:
        manutencoes = manutencoes.filter(data_registro__month=mes)
    if ano:
        manutencoes = manutencoes.filter(data_registro__year=ano)
    if of_id:
        manutencoes = manutencoes.filter(oficina_id=of_id)

    manutencoes = manutencoes.order_by("data_registro")

    # Monta título do período
    MESES_PT = {
        "1":"Janeiro","2":"Fevereiro","3":"Março","4":"Abril",
        "5":"Maio","6":"Junho","7":"Julho","8":"Agosto",
        "9":"Setembro","10":"Outubro","11":"Novembro","12":"Dezembro",
    }
    if mes and ano:
        periodo = f"{MESES_PT.get(mes, mes)}/{ano}"
    elif mes:
        periodo = MESES_PT.get(mes, mes)
    elif ano:
        periodo = ano
    else:
        periodo = "Geral"

    nome_arquivo = f"relatorio_manutencao_{periodo.replace('/', '_')}.pdf"
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'

    doc    = SimpleDocTemplate(response, pagesize=landscape(A4),
                               leftMargin=1.5*cm, rightMargin=1.5*cm,
                               topMargin=1*cm, bottomMargin=1.5*cm)
    styles = getSampleStyleSheet()
    story  = []

    # ── Logo + Título lado a lado ─────────────────────────────────────────────
    from django.apps import apps
    app_path  = apps.get_app_config("manutencao").path
    logo_path = os.path.join(app_path, "static", "img", "logo.png")

    titulo_style = ParagraphStyle(
        "titulo", parent=styles["Heading1"],
        fontSize=15, alignment=TA_CENTER, spaceAfter=4,
        textColor=colors.HexColor("#1e3a5f"),
    )
    subtitulo_style = ParagraphStyle(
        "subtitulo", parent=styles["Normal"],
        fontSize=8, alignment=TA_CENTER, spaceAfter=10,
        textColor=colors.grey,
    )
    periodo_style = ParagraphStyle(
        "periodo", parent=styles["Heading2"],
        fontSize=11, alignment=TA_CENTER,
        textColor=colors.HexColor("#2d4a6e"), spaceAfter=3,
    )

    titulo_bloco = [
        Paragraph("Sistema de Controle de Manutenção", titulo_style),
        Paragraph(f"Relatório de Manutenções — Período: {periodo}", periodo_style),
        Paragraph(
            f"Gerado em {timezone.now().strftime('%d/%m/%Y às %H:%M')} "
            f"por {request.user.get_full_name() or request.user.username}",
            subtitulo_style
        ),
    ]

    if os.path.exists(logo_path):
        logo = Image(logo_path, width=4.5*cm, height=1.8*cm)
        cabecalho = Table(
            [[logo, titulo_bloco]],
            colWidths=[5*cm, None],
        )
        cabecalho.setStyle(TableStyle([
            ("VALIGN",  (0,0), (-1,-1), "MIDDLE"),
            ("ALIGN",   (0,0), (0,0),   "LEFT"),
            ("ALIGN",   (1,0), (1,0),   "CENTER"),
            ("LEFTPADDING",  (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING",   (0,0), (-1,-1), 0),
            ("BOTTOMPADDING",(0,0), (-1,-1), 0),
        ]))
        story.append(cabecalho)
    else:
        for item in titulo_bloco:
            story.append(item)

    story.append(Spacer(1, 0.4*cm))

    # ── Cards de resumo ───────────────────────────────────────────────────────
    total      = Manutencao.objects.count()
    pendentes  = Manutencao.objects.filter(status="pendente").count()
    atrasadas  = Manutencao.objects.filter(status="atrasada").count()
    concluidas = Manutencao.objects.filter(status="concluida").count()

    resumo_data = [
        ["Total", "Pendentes", "Atrasadas", "Concluídas"],
        [str(total), str(pendentes), str(atrasadas), str(concluidas)],
    ]
    resumo_table = Table(resumo_data, colWidths=[4*cm]*4)
    resumo_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), colors.HexColor("#1e3a5f")),
        ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 10),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("BACKGROUND",    (0,1), (-1,1), colors.HexColor("#f0f4f8")),
        ("BOX",           (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e0")),
        ("INNERGRID",     (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e0")),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(resumo_table)
    story.append(Spacer(1, 0.6*cm))

    # ── Tabela de manutenções ─────────────────────────────────────────────────
    story.append(Paragraph("Detalhamento das Manutenções", styles["Heading2"]))
    story.append(Spacer(1, 0.3*cm))

    header = ["Equipamento", "Tipo", "Descrição", "Registro", "Prev.", "Horímetro", "Oficina", "Status", "Resp.", "Dias"]
    rows   = [header]

    STATUS_CORES = {
        "aguardando_orcamento": colors.HexColor("#fefcbf"),
        "orcamento_aprovado":   colors.HexColor("#bee3f8"),
        "concluida":            colors.HexColor("#c6f6d5"),
    }

    for m in manutencoes:
        dias      = f"{m.dias_ate_conclusao}d" if m.dias_ate_conclusao is not None else "—"
        horimetro = f"{m.horimetro} h" if m.horimetro is not None else "—"
        oficina   = m.oficina.nome if m.oficina else "—"
        rows.append([
            m.equipamento.nome,
            m.get_tipo_display(),
            m.descricao[:35] + ("…" if len(m.descricao) > 35 else ""),
            m.data_registro.strftime("%d/%m/%Y"),
            m.data_prevista.strftime("%d/%m/%Y"),
            horimetro,
            oficina,
            m.get_status_display(),
            m.responsavel or "—",
            dias,
        ])

    col_widths = [3.8*cm, 2.2*cm, 5.5*cm, 2.4*cm, 2.4*cm, 2.0*cm, 3.0*cm, 2.2*cm, 2.8*cm, 1.8*cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)

    style_cmds = [
        ("BACKGROUND",    (0,0), (-1,0),  colors.HexColor("#1e3a5f")),
        ("TEXTCOLOR",     (0,0), (-1,0),  colors.white),
        ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 8),
        ("ALIGN",         (0,0), (-1,-1), "LEFT"),
        ("ALIGN",         (3,0), (5,-1),  "CENTER"),
        ("ALIGN",         (9,0), (9,-1),  "CENTER"),
        ("BOX",           (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e0")),
        ("INNERGRID",     (0,0), (-1,-1), 0.3, colors.HexColor("#e2e8f0")),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, colors.HexColor("#f7fafc")]),
    ]

    for i, m in enumerate(manutencoes, start=1):
        cor = STATUS_CORES.get(m.status, colors.white)
        style_cmds.append(("BACKGROUND", (7, i), (7, i), cor))

    t.setStyle(TableStyle(style_cmds))
    story.append(t)

    # ── Gráfico de % dias parado por equipamento ──────────────────────────────
    # Só gera se houver filtro de mês e ano E manutenções concluídas com dias calculados
    if mes and ano:
        dados_grafico = {}
        total_dias_mes = calendar.monthrange(int(ano), int(mes))[1]

        for m in manutencoes:
            if m.dias_ate_conclusao is not None and m.dias_ate_conclusao > 0:
                nome = m.equipamento.nome
                dados_grafico[nome] = dados_grafico.get(nome, 0) + m.dias_ate_conclusao

        if dados_grafico:
            story.append(Spacer(1, 1*cm))
            story.append(Paragraph("Dias Parado por Equipamento no Mês", styles["Heading2"]))
            story.append(Spacer(1, 0.3*cm))

            # Calcula % em relação aos dias do mês
            equipamentos_nomes = list(dados_grafico.keys())
            dias_valores       = list(dados_grafico.values())
            percentuais        = [round((d / total_dias_mes) * 100, 1) for d in dias_valores]

            # Cores do gráfico
            cores_graf = [
                "#1e3a5f","#2d6a9f","#4a9eca","#68b8e0",
                "#f6ad55","#fc8181","#68d391","#b794f4",
            ]
            cores_graf = (cores_graf * 10)[:len(equipamentos_nomes)]

            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
            fig.patch.set_facecolor("#f0f4f8")

            # Gráfico de pizza
            wedges, texts, autotexts = ax1.pie(
                dias_valores,
                labels=None,
                autopct="%1.1f%%",
                colors=cores_graf,
                startangle=90,
                wedgeprops={"edgecolor": "white", "linewidth": 1.5},
            )
            for at in autotexts:
                at.set_fontsize(9)
                at.set_color("white")
                at.set_fontweight("bold")

            ax1.set_title(
                f"Proporção de dias parados\n({MESES_PT.get(mes, mes)}/{ano})",
                fontsize=11, fontweight="bold", color="#1e3a5f", pad=12
            )

            # Legenda do pizza
            patches = [
                mpatches.Patch(color=cores_graf[i], label=f"{equipamentos_nomes[i]} ({dias_valores[i]}d)")
                for i in range(len(equipamentos_nomes))
            ]
            ax1.legend(handles=patches, loc="lower center",
                       bbox_to_anchor=(0.5, -0.18), ncol=2, fontsize=8,
                       framealpha=0.8)

            # Gráfico de barras — % dos dias do mês
            bars = ax2.barh(equipamentos_nomes, percentuais, color=cores_graf, edgecolor="white")
            ax2.set_xlabel("% dos dias do mês", fontsize=9, color="#4a5568")
            ax2.set_title(
                f"% de dias parados sobre {total_dias_mes} dias do mês",
                fontsize=11, fontweight="bold", color="#1e3a5f", pad=12
            )
            ax2.set_xlim(0, max(percentuais) * 1.25)
            ax2.set_facecolor("#f7fafc")
            ax2.tick_params(labelsize=9)
            ax2.spines["top"].set_visible(False)
            ax2.spines["right"].set_visible(False)

            for bar, pct in zip(bars, percentuais):
                ax2.text(
                    bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                    f"{pct}%", va="center", fontsize=9,
                    color="#1e3a5f", fontweight="bold"
                )

            plt.tight_layout(pad=2)

            # Salva o gráfico em memória e insere no PDF
            buf = io.BytesIO()
            plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                        facecolor=fig.get_facecolor())
            plt.close(fig)
            buf.seek(0)

            img = Image(buf, width=22*cm, height=9*cm)
            story.append(img)

            # Tabela resumo abaixo do gráfico
            story.append(Spacer(1, 0.5*cm))
            resumo_rows = [["Equipamento", "Dias parados", f"% dos {total_dias_mes} dias do mês"]]
            for i, nome in enumerate(equipamentos_nomes):
                resumo_rows.append([nome, f"{dias_valores[i]} dia(s)", f"{percentuais[i]}%"])

            resumo_t = Table(resumo_rows, colWidths=[9*cm, 4*cm, 6*cm])
            resumo_t.setStyle(TableStyle([
                ("BACKGROUND",    (0,0), (-1,0), colors.HexColor("#1e3a5f")),
                ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
                ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
                ("FONTSIZE",      (0,0), (-1,-1), 9),
                ("ALIGN",         (1,0), (-1,-1), "CENTER"),
                ("BOX",           (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e0")),
                ("INNERGRID",     (0,0), (-1,-1), 0.3, colors.HexColor("#e2e8f0")),
                ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, colors.HexColor("#f7fafc")]),
                ("TOPPADDING",    (0,0), (-1,-1), 5),
                ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ]))
            story.append(resumo_t)

    # ── Rodapé em todas as páginas ────────────────────────────────────────────
    def rodape(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#718096"))

        # Linha separadora
        canvas.setStrokeColor(colors.HexColor("#cbd5e0"))
        canvas.setLineWidth(0.5)
        canvas.line(2*cm, 1.4*cm, landscape(A4)[0] - 2*cm, 1.4*cm)

        # Texto de contato centralizado
        texto = "📞 Telefone / WhatsApp: 77 9 8856-3082     ✉ Email: cristhianobastos@gmail.com"
        canvas.drawCentredString(landscape(A4)[0] / 2, 1.0*cm, texto)

        # Número da página à direita
        canvas.drawRightString(
            landscape(A4)[0] - 2*cm, 1.0*cm,
            f"Página {doc.page}"
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=rodape, onLaterPages=rodape)
    return response