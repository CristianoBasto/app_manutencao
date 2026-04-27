from django.urls import path
from django.contrib import admin
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth import views as auth_views
from . import views
 
# Bloqueia acesso ao admin para não-administradores
admin.site.login = user_passes_test(
    lambda u: u.is_active and u.is_staff,
    login_url="/login/"
)(admin.site.login)



urlpatterns = [
    # Autenticação
    path("login/",  auth_views.LoginView.as_view(template_name="manutencao/login.html"), name="login"),
    path("login/", auth_views.LoginView.as_view(template_name="manutencao/login.html"), name="logout"),

    # path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),

# Páginas principais
    path("",                               views.dashboard,             name="dashboard"),
    path("manutencoes/",                   views.lista_manutencoes,     name="lista_manutencoes"),
    path("manutencoes/cadastrar/",         views.cadastrar_manutencao,  name="cadastrar_manutencao"),
    path("manutencoes/<int:pk>/editar/",   views.editar_manutencao,     name="editar_manutencao"),
    path("manutencoes/<int:pk>/concluir/", views.concluir_manutencao,   name="concluir_manutencao"),
    path("equipamentos/cadastrar/",        views.cadastrar_equipamento, name="cadastrar_equipamento"),
 
    # Oficinas
    path("oficinas/",           views.lista_oficinas,    name="lista_oficinas"),
    path("oficinas/cadastrar/", views.cadastrar_oficina, name="cadastrar_oficina"),
 
    # Relatório PDF
    path("relatorio/pdf/", views.exportar_pdf, name="exportar_pdf"),
]