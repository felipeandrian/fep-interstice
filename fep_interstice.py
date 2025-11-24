import socket       # Biblioteca padrão para comunicação de rede (TCP/UDP)
import threading    # Permite rodar o 'Ouvido' (Listener) e a 'Boca' (Sender) simultaneamente
import time         # Usado para controlar o ritmo de envio (Jitter) e evitar congestionamento
import select       # Gerencia múltiplos sockets de uma vez (I/O Multiplexing) de forma eficiente
import sys          # Acesso a funções do sistema (como stdout e argv)
import datetime     # Para pegar a hora atual para os logs do chat
import os           # Para interagir com o sistema operacional (limpar tela 'cls'/'clear')

# ==============================================================================
#  CONFIGURAÇÕES VISUAIS (UI/UX)
#  Define códigos de escape ANSI para colorir o terminal e manipular o cursor.
# ==============================================================================

RESET   = "\033[0m"    # Reseta a cor para o padrão do terminal
BOLD    = "\033[1m"    # Texto em negrito
GREEN   = "\033[92m"   # Cor Verde (Usado para identificar o próprio usuário 'Você')
CYAN    = "\033[96m"   # Cor Ciano (Usado para identificar o 'Amigo')
YELLOW  = "\033[93m"   # Cor Amarela (Usado para mensagens de Sistema/Alerta)
GRAY    = "\033[90m"   # Cor Cinza (Usado para timestamps e bordas)
RED     = "\033[91m"   # Cor Vermelha (Usado para erros)
CL_LINE = "\033[K"     # Sequência de escape: Limpa a linha atual do cursor até o fim
UP_LINE = "\033[F"     # Sequência de escape: Move o cursor para a linha de cima
C_BORDER = "\033[90m"  # Cinza Escuro usado para o menu
C_TITLE  = "\033[95m"  # Magenta/Roxo usado para o menu

# --- VARIÁVEIS GLOBAIS ---
# Armazenam o estado da identidade do usuário e controle de execução
MY_NICK = "Eu"            # Nickname padrão do usuário local
PEER_NICK = "Desconhecido" # Nickname padrão do usuário remoto
RUNNING = True            # Flag de controle para manter os loops rodando (Thread Safety)

# --- REDE (Lógica do Protocolo Proprietário) ---
# Mapeia pares de bits (2 bits) para um offset de porta (0 a 3).
# Exemplo: Se quero enviar '00', mando na porta Base + 0. Se '11', Base + 3.
MAPA_BITS = {'00': 0, '01': 1, '10': 2, '11': 3}
# Cria o mapa reverso para decodificação (Offset -> Bits)
MAPA_PORTAS = {v: k for k, v in MAPA_BITS.items()}

def get_time():
    """Retorna a hora atual formatada como HH:MM (String)."""
    return datetime.datetime.now().strftime("%H:%M")

# ==============================================================================
#  INTERFACE (Funções de Renderização de Tela)
# ==============================================================================

def print_header(ip_destino, minha_base, destino_base):
    """
    Limpa a tela e desenha o cabeçalho estático com informações da sessão.
    """
    # Detecta o SO para usar o comando correto de limpar tela
    os.system('cls' if os.name == 'nt' else 'clear')
    
    # Imprime o banner usando as cores definidas
    print(f"{C_BORDER}╔════════════════════════════════════════════════════╗{RESET}")
    print(f"{C_BORDER}║   {C_TITLE}      F E P   I N T E R S T I C E   C H A T      {C_BORDER}║{RESET}")
    print(f"{C_BORDER}╠════════════════════════════════════════════════════╣{RESET}")
    print(f"{C_BORDER}║ {GRAY}  Temporal Gap & Port Hopping Communication Tool   {C_BORDER}║{RESET}")
    print(f"{C_BORDER}╚════════════════════════════════════════════════════╝{RESET}")
    
    # Exibe configurações da sessão atual
    print(f"\n  {BOLD}Operador:{RESET} {GREEN}{MY_NICK}{RESET}")
    print(f"  {BOLD}Vetor:{RESET}    {minha_base} ⇄ {destino_base} (UDP)")
    print(f"  {BOLD}Alvo:{RESET}     {CYAN}{PEER_NICK}{RESET} @ {ip_destino}")
    print(f"  {BOLD}Comandos:{RESET} /cls, /nick, /quit")
    print(f"\n{GRAY} [ STATUS: ENCRIPTADO | CANAL: {minha_base}-{minha_base+3} ]{RESET}")
    print(f"{C_BORDER}------------------------------------------------------{RESET}\n")
    
    # Prepara a linha de input do usuário (Prompt) sem pular linha
    sys.stdout.write(f"{GREEN}{MY_NICK}:{RESET} ")
    sys.stdout.flush() # Força a exibição imediata no buffer

def print_msg_sistema(msg, tipo="INFO"):
    """Imprime mensagens de sistema sem quebrar o fluxo visual do chat."""
    cor = YELLOW if tipo == "INFO" else RED
    # \r volta ao início da linha, CL_LINE apaga o prompt atual, imprime a msg, e redesenha o prompt na próxima linha
    sys.stdout.write(f"\r{CL_LINE}{GRAY}[SYSTEM] {cor} {msg}{RESET}\n{GREEN}{MY_NICK}:{RESET} ")
    sys.stdout.flush()

def print_msg_recebida(msg):
    """Imprime mensagens recebidas do parceiro."""
    # \a toca o som de 'bell' do sistema (aviso sonoro)
    sys.stdout.write(f"\r{CL_LINE}\a{GRAY}[{get_time()}] {CYAN}{BOLD}{PEER_NICK}:{RESET} {msg}\n{GREEN}{MY_NICK}:{RESET} ")
    sys.stdout.flush()

def print_msg_enviada(msg):
    """Formata a mensagem que o próprio usuário enviou."""
    # UP_LINE sobe o cursor para apagar o input 'cru' que o usuário digitou e substituir pela versão formatada
    sys.stdout.write(f"{UP_LINE}{CL_LINE}\r{GRAY}[{get_time()}] {GREEN}{BOLD}{MY_NICK}:{RESET} {msg}\n{GREEN}{MY_NICK}:{RESET} ")
    sys.stdout.flush()

# ==============================================================================
#  REDE (Camada de Transporte e Codificação)
# ==============================================================================

def text_to_bits(text):
    """Converte uma string de texto em uma sequência binária (0s e 1s)."""
    try:
        # Converte string -> bytes (utf-8) -> int -> binário
        bits = bin(int.from_bytes(text.encode('utf-8', 'surrogatepass'), 'big'))[2:]
        # Adiciona padding (zeros à esquerda) para garantir múltiplos de 8 bits (bytes completos)
        return bits.zfill(8 * ((len(bits) + 7) // 8))
    except: return ""

def bits_to_text(bits):
    """Converte uma sequência binária de volta para string de texto."""
    try:
        n = int(bits, 2)
        # Converte int -> bytes -> decodifica utf-8
        return n.to_bytes((n.bit_length() + 7) // 8, 'big').decode('utf-8', 'surrogatepass')
    except: return "?"

def thread_listener(porta_base):
    """
    Thread que roda em background escutando nas 4 portas designadas.
    Responsável por receber os 'sinais' e reconstruir a mensagem.
    """
    sockets = []
    # Abre 4 sockets UDP (Ex: 9000, 9001, 9002, 9003)
    for i in range(4):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # SO_REUSEADDR permite reusar a porta imediatamente se o script for reiniciado (evita erro 'Address already in use')
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setblocking(0) # Define como não-bloqueante para usar com select()
        try:
            s.bind(('0.0.0.0', porta_base + i)) # Vincula a todas as interfaces locais
            sockets.append(s)
        except: pass # Ignora falhas de bind individuais

    if not sockets:
        print_msg_sistema(f"ERRO CRÍTICO: Portas {porta_base}-{porta_base+3} ocupadas!", "ERRO")
        return

    buffer_bits = "" # Buffer para acumular os bits recebidos
    
    while RUNNING: # Loop principal da thread de escuta
        try:
            # select.select monitora eficientemente quais sockets têm dados prontos para leitura
            # Timeout de 0.2s evita uso excessivo de CPU
            readable, _, _ = select.select(sockets, [], [], 0.2)
            
            for s in readable:
                data, _ = s.recvfrom(64) # Lê o pacote (o conteúdo 'X' é irrelevante, mas precisamos ler para limpar o buffer)
                
                # Protocolo de Fim de Mensagem: Se receber 'FIN', processa o que acumulou
                if data == b'FIN':
                    if buffer_bits:
                        texto = ""
                        try:
                            # Loop para converter cada grupo de 8 bits em um caractere
                            while len(buffer_bits) >= 8:
                                byte = buffer_bits[:8]          # Pega 8 bits
                                buffer_bits = buffer_bits[8:]   # Remove do buffer
                                texto += bits_to_text(byte)     # Converte
                            if texto: print_msg_recebida(texto) # Exibe na tela
                        except: pass
                        buffer_bits = "" # Limpa o buffer para a próxima mensagem
                    continue

                # Lógica Core: Mapeia a PORTA recebida para BITS
                porta_recebida = s.getsockname()[1]
                offset = porta_recebida - porta_base # Calcula qual socket foi (0, 1, 2 ou 3)
                buffer_bits += MAPA_PORTAS.get(offset, "") # Adiciona os bits correspondentes (ex: '01')
        except: pass

# --- FUNÇÃO DE COMANDOS INTERNOS (Slash Commands) ---
def processar_comando(cmd, ip_dest, porta_base, minha_base):
    global MY_NICK, RUNNING # Referencia variáveis globais para modificação
    
    parts = cmd.split()
    base = parts[0].lower()
    
    if base == "/cls":
        # Limpa a tela e redesenha o cabeçalho
        print_header(ip_dest, minha_base, porta_base)
    elif base == "/quit":
        print_msg_sistema("Encerrando conexões...", "INFO")
        RUNNING = False # Sinaliza para todas as threads pararem
        time.sleep(0.5)
        sys.exit(0)
    elif base == "/nick":
        if len(parts) > 1:
            MY_NICK = parts[1]
            print_msg_sistema(f"Nick alterado para {MY_NICK}", "INFO")
        else:
            print_msg_sistema("Uso: /nick NovoNome", "ERRO")
    else:
        print_msg_sistema("Comando desconhecido. Use /cls, /nick, /quit", "ERRO")

def loop_sender(ip_destino, porta_destino_base, minha_base_escuta):
    """
    Loop principal de envio (Roda na Main Thread). Lê input e dispara pacotes UDP.
    """
    global RUNNING
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # Socket para envio (não precisa de bind)
    
    while RUNNING:
        try:
            msg = input() # Bloqueia esperando o usuário digitar e dar Enter
            
            if not msg:
                # Se o usuário der Enter vazio, apenas restaura o prompt visualmente
                sys.stdout.write(f"{UP_LINE}{CL_LINE}\r{GREEN}{MY_NICK}:{RESET} ")
                sys.stdout.flush()
                continue

            # --- VERIFICAÇÃO DE COMANDOS INTERNOS ---
            if msg.startswith("/"):
                processar_comando(msg, ip_destino, porta_destino_base, minha_base_escuta)
                continue

            # --- PROCESSO DE ENVIO ---
            print_msg_enviada(msg) # Atualiza a UI
            
            # 1. Converte texto para bits
            bits = text_to_bits(msg)
            if len(bits) % 2 != 0: bits += "0" # Padding se necessário para formar pares
            
            # 2. Agrupa em pares de 2 bits (00, 01, 10, 11)
            pares = [bits[i:i+2] for i in range(0, len(bits), 2)]
            
            # 3. Dispara os pacotes (Bit-Banging via Portas)
            for par in pares:
                offset = MAPA_BITS[par] # Descobre o offset (ex: '10' -> offset 2)
                # Envia lixo ('X') para a porta calculada
                sock.sendto(b'X', (ip_destino, porta_destino_base + offset))
                # Delay minúsculo para garantir ordem de chegada e evitar congestionamento UDP
                time.sleep(0.02) 
            
            # 4. Envia Sinal de Fim (FIN)
            # Envia 3 vezes para redundância (UDP não garante entrega)
            for _ in range(3):
                sock.sendto(b'FIN', (ip_destino, porta_destino_base))
                time.sleep(0.01)

        except KeyboardInterrupt:
            print(f"\n{YELLOW}Encerrando...{RESET}")
            RUNNING = False
            sys.exit()
        except: pass

# ==============================================================================
#  MAIN (SETUP E CONFIGURAÇÃO INICIAL)
# ==============================================================================
if __name__ == "__main__":
    os.system('cls' if os.name == 'nt' else 'clear')
    
    # Definição de cores locais para o menu
    C_SYS = "\033[93m"
    
    print(f"{C_SYS}--- CONFIGURAÇÃO DO AGENTE ---{RESET}")
    print("Para funcionar, UM deve ser A e o OUTRO deve ser B.\n")
    
    # Menu de Seleção de Perfil
    print(f" [1] {GREEN}CANAL A{RESET}")
    print(f"     Escuta: 9000, 9001, 9002, 9003")
    print(f"     Fala:   9004, 9005, 9006, 9007")
    print("")
    print(f" [2] {CYAN}CANAL B{RESET}")
    print(f"     Escuta: 9004, 9005, 9006, 9007")
    print(f"     Fala:   9000, 9001, 9002, 9003")
    
    escolha = input("\nEscolha sua identidade (1 ou 2): ")
    
    # LÓGICA CRUZADA DE PORTAS
    # Se eu sou A, escuto na base A e falo na base B.
    if escolha == '1':
        MINHA_BASE = 9000      
        DESTINO_BASE = 9004    
        papel_default = "A"
    else:
        MINHA_BASE = 9004      
        DESTINO_BASE = 9000    
        papel_default = "B"

    # Configuração de Nicks e IP
    print("\n--- PERSONALIZAÇÃO ---")
    input_nick = input(f"Seu Nickname [{papel_default}]: ")
    MY_NICK = input_nick if input_nick else papel_default
    
    input_peer = input(f"Nickname do Parceiro [Amigo]: ")
    PEER_NICK = input_peer if input_peer else "Amigo"

    ip_amigo = input("\nIP do Parceiro (Ex: 10.0.0.X): ")
    if not ip_amigo: ip_amigo = "127.0.0.1"

    # 1. Desenha a Interface
    print_header(ip_amigo, MINHA_BASE, DESTINO_BASE)
    
    # 2. Inicia a Thread de Escuta (Background)
    t = threading.Thread(target=thread_listener, args=(MINHA_BASE,))
    t.daemon = True # Garante que a thread morra se o programa principal fechar
    t.start()
    
    # 3. Inicia o Loop de Envio (Foreground - Bloqueia o terminal para input)
    loop_sender(ip_amigo, DESTINO_BASE, MINHA_BASE)