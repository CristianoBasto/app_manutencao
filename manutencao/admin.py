from django.contrib import admin
from .models import Oficina, Equipamento, Manutencao


@admin.register(Oficina)
class OficinaAdmin(admin.ModelAdmin):
    list_display  = ("nome", "telefone", "responsavel")
    search_fields = ("nome", "responsavel")


class ManutencaoInline(admin.TabularInline):
    """Mostra as manutenções diretamente na página do equipamento."""
    model  = Manutencao
    extra  = 1   # quantas linhas em branco aparecem por padrão
    fields = ("tipo", "descricao", "data_prevista", "status", "responsavel")


@admin.register(Equipamento)
class EquipamentoAdmin(admin.ModelAdmin):
    list_display  = ("nome", "localizacao", "descricao")
    search_fields = ("nome", "localizacao")
    inlines       = [ManutencaoInline]


@admin.register(Manutencao)
class ManutencaoAdmin(admin.ModelAdmin):
    list_display  = ("equipamento", "tipo", "descricao", "data_prevista", "status", "responsavel")
    list_filter   = ("status", "tipo", "equipamento")
    search_fields = ("descricao", "responsavel", "equipamento__nome")
    date_hierarchy = "data_prevista"
    list_editable  = ("status",)   # edita o status direto na listagem