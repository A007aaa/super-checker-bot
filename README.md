# 🚀 Super Checker Bot 2.0 (Elite Edition)

O **Super Checker Bot** é uma ferramenta de alta performance para verificação massiva de saldos em múltiplas blockchains e exchanges centralizadas (CEX). Projetado para ser rápido, seguro e resiliente.

## ⚡ Principais Recursos

- **Suporte Multichain:** Ethereum, BSC, Polygon, Arbitrum, Optimism, Avalanche, Fantom, Solana, Tron e Bitcoin.
- **Integração CEX:** Verificação de saldo via API para **Kraken, KuCoin e Bitfinex**.
- **Modo Hyper Turbo:** Validação matemática de checksum (BIP-39) local antes de consultar a rede, permitindo processar milhares de palavras por segundo.
- **Rotação Inteligente de RPC:** Sistema de fallback automático entre RPCs privados (Alchemy) e públicos de alta qualidade.
- **Resiliência:** Tratamento de erros 429 (Too Many Requests) com backoff exponencial e blacklist temporária.
- **Segurança:** Configuração via variáveis de ambiente e suporte a `.env`.

## 🛠️ Configuração

1. **Clonar o repositório:**
   ```bash
   git clone https://github.com/A007aaa/super-checker-bot.git
   cd super-checker-bot
   ```

2. **Instalar dependências:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configurar variáveis de ambiente:**
   Crie um arquivo `.env` baseado no `.env.example`:
   - `TELEGRAM_BOT_TOKEN`: Seu token do @BotFather.
   - `ALCHEMY_KEY`: (Opcional) Sua chave do Alchemy para performance máxima.

## 🚀 Como Usar

1. Inicie o bot no Telegram com `/start`.
2. Envie uma lista de palavras, um arquivo `.txt` ou chaves de API de CEX no formato:
   - **Kraken/Bitfinex:** `api_key:api_secret`
   - **KuCoin:** `api_key:api_secret:passphrase`
3. Use o comando `/check` para iniciar a varredura ultra-rápida.
4. O bot enviará um relatório em tempo real de qualquer saldo encontrado.

## 🔒 Segurança e Privacidade

- O bot **não armazena** suas seeds ou chaves de API.
- Todo o processamento de derivação de endereços é feito localmente na memória.
- Recomendamos rodar o bot em ambientes seguros como Railway, Heroku ou VPS própria.

---
*Desenvolvido com foco em performance e assertividade.*
