# 🐾 S.O.S Patinhas

O **S.O.S Patinhas** é um projeto acadêmico da **FATEC Ourinhos**, desenvolvido para a disciplina de **Engenharia de Software**.

A plataforma busca apoiar a proteção animal, reunindo informações sobre adoção, denúncias, resgates, doações e voluntariado, além de oferecer um painel administrativo para a ONG.

## Tecnologias utilizadas

- **Python + FastAPI:** backend do sistema, responsável por login, cadastros, regras de adoção e processamento das informações.
- **SQLite:** banco de dados que armazena usuários, animais, denúncias e solicitações.
- **HTML + Jinja2:** estrutura e exibição das páginas.
- **CSS + JavaScript:** aparência, responsividade e interatividade.

## Como executar

### Linux (Zorin OS, Ubuntu ou Mint)

Abra o terminal na pasta do projeto e execute:

```bash
sudo apt install -y python3 python3-venv python3-pip
bash iniciar.sh
```

### Windows

Instale o **Python 3** em [python.org](https://www.python.org/downloads/) e, no PowerShell aberto na pasta do projeto, execute:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Em ambos os sistemas, abra **http://127.0.0.1:8000** no navegador.

### Administrador e demonstração

Para criar uma conta de administrador:

```bash
# Linux
bash iniciar.sh admin
```

```powershell
# Windows
.\.venv\Scripts\python.exe app.py admin
```

Para incluir quatro animais fictícios de demonstração, use o comando `demo` no lugar de `admin`.

## Comparação com a documentação

Veja o [comparativo resumido](COMPARATIVO.md).

## Observação

Este é um **projeto acadêmico de demonstração**. Os animais e as imagens de exemplo são fictícios e não representam animais reais disponíveis para adoção.
