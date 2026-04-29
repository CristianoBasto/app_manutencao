from django.db import models


class Oficina(models.Model):
    nome        = models.CharField(max_length=100)
    telefone    = models.CharField(max_length=20, blank=True)
    responsavel = models.CharField(max_length=100, blank=True)
    criado_por  = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="oficinas_criadas"
    )

    def __str__(self):
        return self.nome

    class Meta:
        verbose_name        = "Oficina"
        verbose_name_plural = "Oficinas"
        ordering            = ["nome"]


class Equipamento(models.Model):
    nome        = models.CharField(max_length=100)
    localizacao = models.CharField(max_length=100)
    descricao   = models.TextField(blank=True)
    criado_por  = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="equipamentos_criados"
    )

    def __str__(self):
        return self.nome

    class Meta:
        verbose_name        = "Equipamento"
        verbose_name_plural = "Equipamentos"
        ordering            = ["nome"]


class Manutencao(models.Model):
    TIPO_CHOICES = [
        ("preventiva", "Preventiva"),
        ("corretiva",  "Corretiva"),
    ]
    STATUS_CHOICES = [
        ("concluida",            "Concluída"),
        ("aguardando_orcamento", "Aguardando Orçamento"),
        ("orcamento_aprovado",   "Orçamento Aprovado"),
    ]

    equipamento    = models.ForeignKey(
        Equipamento,
        on_delete=models.CASCADE,
        related_name="manutencoes"
    )
    tipo           = models.CharField(max_length=20, choices=TIPO_CHOICES)
    descricao      = models.TextField()
    data_registro  = models.DateField(verbose_name="Data de Registro")
    data_prevista  = models.DateField()
    data_realizada = models.DateField(null=True, blank=True)
    status         = models.CharField(max_length=30, choices=STATUS_CHOICES, default="aguardando_orcamento")
    responsavel    = models.CharField(max_length=100, blank=True)
    horimetro      = models.PositiveIntegerField(null=True, blank=True, verbose_name="Horímetro (h)")
    oficina        = models.ForeignKey(
        Oficina,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="manutencoes",
        verbose_name="Oficina"
    )
    criado_por     = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="manutencoes_criadas",
        verbose_name="Criado por"
    )

    def __str__(self):
        return f"{self.equipamento} — {self.tipo} ({self.get_status_display()})"

    @property
    def dias_ate_conclusao(self):
        """Retorna a quantidade de dias entre o registro e a conclusão."""
        if self.data_realizada and self.data_registro:
            return (self.data_realizada - self.data_registro).days
        return None

    class Meta:
        verbose_name        = "Manutenção"
        verbose_name_plural = "Manutenções"
        ordering            = ["data_prevista"]