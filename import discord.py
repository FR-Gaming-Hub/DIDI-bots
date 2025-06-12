import discord
from discord.ext import commands
from discord.ui import View, Button
import json
import os
import asyncio
import re
import random
from datetime import datetime, timezone
from dotenv import load_dotenv

# --- Configuration ---
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = "!"
LOGS_FILE = "logs.json"
WARNS_FILE = "warns.json"

TICKET_CATEGORY_NAME = "Tickets support"
MAX_WARNS = 3


bad_words = ["mot1", "mot2", "mot3", "exemple"]

intents = discord.Intents.all()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)


anti_raid_enabled = False
user_last_message_times = {}

# --- Gestionnaires de Fichiers JSON ---
def init_logs():
    """Initialise le fichier JSON des logs s'il n'existe pas ou s'il est vide/corrompu."""
    if not os.path.exists(LOGS_FILE) or os.path.getsize(LOGS_FILE) == 0:
        with open(LOGS_FILE, "w", encoding="utf-8") as f:
            json.dump({"actions": []}, f, indent=4)
    else:
        try:
            with open(LOGS_FILE, "r", encoding="utf-8") as f:
                json.load(f)
        except json.JSONDecodeError:
            print(f"Warning: {LOGS_FILE} is corrupted. Reinitializing it.")
            with open(LOGS_FILE, "w", encoding="utf-8") as f:
                json.dump({"actions": []}, f, indent=4)

def init_warns():
    """Initialise le fichier JSON des avertissements s'il n'existe pas ou s'il est vide/corrompu."""
    if not os.path.exists(WARNS_FILE) or os.path.getsize(WARNS_FILE) == 0:
        with open(WARNS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)
    else:
        try:
            with open(WARNS_FILE, "r", encoding="utf-8") as f:
                json.load(f)
        except json.JSONDecodeError:
            print(f"Warning: {WARNS_FILE} is corrupted. Reinitializing it.")
            with open(WARNS_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=4)

def log_action(action_type, user, target=None, reason=None, duration=None, details=None):
    """Enregistre les actions de modération dans un fichier JSON."""
    init_logs()
    with open(LOGS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    entry = {
        "action": action_type,
        "moderator": str(user),
        "target": str(target) if target else None,
        "reason": reason,
        "duration": duration,
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    data["actions"].append(entry)
    with open(LOGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

# --- Fonctions du Système d'Avertissement ---
def load_warns():
    """Charge les données d'avertissement du fichier JSON."""
    init_warns()
    with open(WARNS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_warns(data):
    """Sauvegarde les données d'avertissement dans le fichier JSON."""
    with open(WARNS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def add_warn(user_id, reason):
    """Ajoute un avertissement à un utilisateur et retourne son nombre actuel d'avertissements."""
    warns = load_warns()
    user_id_str = str(user_id)
    warns.setdefault(user_id_str, []).append({"reason": reason, "timestamp": datetime.now(timezone.utc).isoformat()})
    save_warns(warns)
    return len(warns[user_id_str])

def reset_warns(user_id):
    """Réinitialise tous les avertissements d'un utilisateur spécifique."""
    warns = load_warns()
    warns[str(user_id)] = []
    save_warns(warns)

def get_warns_count(user_id):
    """Obtient le nombre actuel d'avertissements pour un utilisateur spécifique."""
    warns = load_warns()
    return len(warns.get(str(user_id), []))

# --- Vérification des Permissions ---
def is_admin():
    """Décorateur pour vérifier si l'invocateur de la commande a les permissions d'administrateur."""
    async def predicate(ctx):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("🚫 Vous n'avez pas la permission d'utiliser cette commande (Administrateur requis).", ephemeral=True)
            return False
        return True
    return commands.check(predicate)

# --- Analyseur de Durée ---
def parse_duration(duration_str):
    """Analyse une chaîne de durée (par exemple, '10s', '5m', '1h', '2d') en secondes."""
    match = re.fullmatch(r"(\d+)([smhd])", duration_str.lower())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    return value * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]

# --- Commandes de Modération ---
@bot.command()
@is_admin()
async def kick(ctx, member: discord.Member, *, reason=None):
    """Expulse un membre du serveur."""
    try:
        await member.kick(reason=reason)
        await ctx.send(f"👢 **{member}** a été expulsé. Raison : {reason or 'Aucune'}")
        log_action("kick", ctx.author, member, reason)
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas les permissions de faire ça. Veuillez vérifier mes rôles.")
    except Exception as e:
        await ctx.send(f"Erreur lors de l'expulsion : {e}")

@bot.command()
@is_admin()
async def ban(ctx, member: discord.Member, *, reason=None):
    """Bannit un membre du serveur."""
    try:
        await member.ban(reason=reason)
        await ctx.send(f"🔨 **{member}** a été banni. Raison : {reason or 'Aucune'}")
        log_action("ban", ctx.author, member, reason)
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas les permissions de faire ça. Veuillez vérifier mes rôles.")
    except Exception as e:
        await ctx.send(f"Erreur lors du bannissement : {e}")

@bot.command()
@is_admin()
async def unban(ctx, *, member_identifier):
    """Débannit un utilisateur par son nom#tag ou son ID."""
    banned_users = await ctx.guild.bans()
    member_identifier = member_identifier.strip()

    for ban_entry in banned_users:
        user = ban_entry.user
        if (f"{user.name}#{user.discriminator}".lower() == member_identifier.lower() or
            str(user.id) == member_identifier):
            try:
                await ctx.guild.unban(user)
                await ctx.send(f"✅ **{user}** a été débanni.")
                log_action("unban", ctx.author, user)
                return
            except discord.Forbidden:
                await ctx.send("❌ Je n'ai pas les permissions de faire ça. Veuillez vérifier mes rôles.")
                return
            except Exception as e:
                await ctx.send(f"Erreur lors du débannissement : {e}")
                return
    await ctx.send(f"Utilisateur `{member_identifier}` introuvable dans la liste des bannissements.")

@bot.command()
@is_admin()
async def clear(ctx, amount: int):
    """Supprime un nombre spécifié de messages du salon actuel."""
    if amount <= 0:
        await ctx.send("Nombre de messages invalide.")
        return
    try:
        # +1 pour inclure le message de commande lui-même, puis le supprimer
        deleted = await ctx.channel.purge(limit=amount + 1)
        await ctx.send(f"✅ **{len(deleted)-1}** messages supprimés.", delete_after=5)
        log_action("clear", ctx.author, details=f"{len(deleted)-1} messages supprimés dans {ctx.channel.name}")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas les permissions de supprimer les messages dans ce salon.")
    except Exception as e:
        await ctx.send(f"Erreur lors de la suppression des messages : {e}")

@bot.command()
@is_admin()
async def warn(ctx, member: discord.Member, *, reason="Aucune raison fournie"):
    """Avertit un membre. Bannissement automatique après MAX_WARNS."""
    count = add_warn(member.id, reason)
    await ctx.send(f"⚠️ **{member}** a été averti (**{count}/{MAX_WARNS}**). Raison : **{reason}**")
    log_action("warn", ctx.author, member, reason)
    if count >= MAX_WARNS:
        try:
            await member.ban(reason=f"Bannissement automatique après {MAX_WARNS} avertissements")
            await ctx.send(f"🚫 **{member}** a été automatiquement banni après **{MAX_WARNS}** avertissements.")
            log_action("ban", bot.user, member, f"Bannissement automatique après {MAX_WARNS} avertissements")
        except discord.Forbidden:
            await ctx.send(f"❌ Impossible de bannir {member} automatiquement (permissions manquantes).")
        except Exception as e:
            await ctx.send(f"Erreur lors du bannissement automatique : {e}")

@bot.command()
@is_admin()
async def unwarn(ctx, member: discord.Member):
    """Supprime tous les avertissements pour un membre."""
    reset_warns(member.id)
    await ctx.send(f"✅ Tous les avertissements pour **{member}** ont été supprimés.")
    log_action("unwarn", ctx.author, member)

# --- Système de Sourdine (Mute) ---
# NOTE: Le mute à l'échelle du serveur en changeant les permissions de chaque canal est lourd.
# Pour les grands serveurs, un rôle "Muet" avec des permissions spécifiques est préférable.
# Cependant, pour garder la simplicité et la fonctionnalité, je maintiens la version actuelle.
async def apply_server_mute(ctx, member):
    """Applique une sourdine à l'échelle du serveur en définissant les permissions dans tous les canaux."""
    for channel in ctx.guild.channels:
        try:
            # Écraser les permissions pour empêcher d'envoyer des messages et de parler
            await channel.set_permissions(member, send_messages=False, speak=False, add_reactions=False)
        except discord.Forbidden:
            print(f"DEBUG: Impossible de définir les permissions de mute pour {member} dans {channel.name} (Forbidden).")
        except Exception as e:
            print(f"DEBUG: Erreur lors de l'application du mute pour {member} dans {channel.name}: {e}")

async def remove_server_mute(ctx, member):
    """Supprime la sourdine à l'échelle du serveur en réinitialisant les permissions des canaux."""
    for channel in ctx.guild.channels:
        try:
            # Effacer toutes les surcharges spécifiques pour le membre dans ce canal
            await channel.set_permissions(member, overwrite=None)
        except discord.Forbidden:
            print(f"DEBUG: Impossible de réinitialiser les permissions de mute pour {member} dans {channel.name} (Forbidden).")
        except Exception as e:
            print(f"DEBUG: Erreur lors de la suppression du mute pour {member} dans {channel.name}: {e}")

@bot.command()
@is_admin()
async def mute(ctx, member: discord.Member, *, reason=None):
    """Rend un membre muet sur tout le serveur."""
    try:
        await apply_server_mute(ctx, member)
        await ctx.send(f"🔇 **{member.mention}** a été rendu muet. Raison : {reason or 'Aucune'}")
        log_action("mute", ctx.author, member, reason)
    except Exception as e:
        await ctx.send(f"Erreur lors du mute : {e}")

@bot.command()
@is_admin()
async def unmute(ctx, member: discord.Member):
    """Rend un membre non muet sur tout le serveur."""
    try:
        await remove_server_mute(ctx, member)
        await ctx.send(f"🔊 **{member.mention}** n'est plus muet.")
        log_action("unmute", ctx.author, member)
    except Exception as e:
        await ctx.send(f"Erreur lors de l'unmute : {e}")

@bot.command()
@is_admin()
async def tempmute(ctx, member: discord.Member, duration: str, *, reason=None):
    """Rend un membre temporairement muet pour une durée spécifiée."""
    seconds = parse_duration(duration)
    if seconds is None:
        await ctx.send("❌ Format de durée invalide. Utilisez : `10s`, `5m`, `1h`, `2d`")
        return
    try:
        await apply_server_mute(ctx, member)
        await ctx.send(f"⏳ **{member.mention}** a été rendu muet pour **{duration}**.")
        log_action("tempmute", ctx.author, member, reason, duration)
        await asyncio.sleep(seconds)
        # Vérifier si le membre est toujours dans le serveur avant de le rendre non muet
        if member in ctx.guild.members:
            await remove_server_mute(ctx, member)
            await ctx.send(f"🔊 **{member.mention}** n'est plus muet après **{duration}**.")
            log_action("tempunmute", bot.user, member, f"Sourdine temporaire terminée après {duration}")
    except Exception as e:
        await ctx.send(f"Erreur lors du tempmute : {e}")

# --- Vue de Confirmation d'Envoi de Message en Masse ---
class ConfirmSendView(View):
    def __init__(self, ctx, message):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.message = message
        # Empêcher les interactions après le premier clic
        self.confirmed = False

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("❌ Ce bouton n'est pas pour vous.", ephemeral=True)
            return
        
        if self.confirmed: # Éviter les doubles clics
            await interaction.response.send_message("Cette action est déjà en cours ou a été complétée.", ephemeral=True)
            return
        self.confirmed = True

        await interaction.response.send_message("🚀 Envoi en cours...", ephemeral=True) # Répondre à l'interaction rapidement

        count, failed = 0, 0
        # Désactiver les boutons après le clic pour éviter les problèmes
        self.children[0].disabled = True
        self.children[1].disabled = True
        await interaction.message.edit(view=self)

        for member in self.ctx.guild.members:
            if member.bot:
                continue
            try:
                await member.send(self.message)
                count += 1
                await asyncio.sleep(0.5) # Petite pause pour éviter le rate limit de Discord
            except discord.Forbidden:
                failed += 1
                print(f"DEBUG: Impossible d'envoyer un DM à {member.name} (Forbidden).")
            except Exception as e:
                failed += 1
                print(f"DEBUG: Échec de l'envoi de DM à {member.name}: {e}")

        await self.ctx.send(f"✅ Message envoyé à **{count}** membres. Échecs : **{failed}**")
        log_action("mass_dm", self.ctx.author, details=f"Envoyé à {count} membres, {failed} échecs")
        self.stop() # Arrêter la vue après l'envoi

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("❌ Ce bouton n'est pas pour vous.", ephemeral=True)
            return
        if self.confirmed: # Si déjà confirmé, l'annulation n'a plus de sens
            await interaction.response.send_message("Action déjà en cours, impossible d'annuler.", ephemeral=True)
            return
        
        await interaction.response.send_message("❌ Envoi annulé.", ephemeral=True)
        # Désactiver les boutons
        self.children[0].disabled = True
        self.children[1].disabled = True
        await interaction.message.edit(view=self)
        self.stop()

@bot.command()
@is_admin()
async def sendall(ctx, *, message):
    """Envoie un message privé à tous les membres du serveur (nécessite confirmation)."""
    embed = discord.Embed(
        title="⚠️ Confirmation d'envoi de message en masse",
        description=f"Êtes-vous sûr de vouloir envoyer le message suivant à **tous les membres** du serveur ?\n\n```\n{message}\n```\n\n**Ceci est irréversible !**",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed, view=ConfirmSendView(ctx, message))

# --- Système de Giveaways ---
giveaways = {} # {message_id: {details}} - (Note : ceci n'est pas persistant après un redémarrage du bot)

@bot.command()
@is_admin()
async def giveaway(ctx, duration: str, *, prize):
    """Démarre un concours pour une durée et un prix spécifiés."""
    seconds = parse_duration(duration)
    if seconds is None:
        await ctx.send("❌ Format de durée invalide. Utilisez : `10s`, `5m`, `1h`, `2d`")
        return
    
    # Création d'un Embed plus esthétique pour le giveaway
    embed = discord.Embed(
        title="🎉 Giveaway en Cours ! 🎉",
        description=f"Réagissez avec 🎉 pour tenter de gagner : **{prize}**",
        color=discord.Color.gold()
    )
    embed.add_field(name="⏰ Durée restante", value=f"`{duration}`", inline=False)
    embed.set_footer(text=f"Organisé par {ctx.author.display_name}")
    embed.timestamp = datetime.now(timezone.utc)

    giveaway_message = await ctx.send(embed=embed)
    await giveaway_message.add_reaction("🎉")

    giveaways[giveaway_message.id] = {
        "channel_id": ctx.channel.id,
        "prize": prize,
        "end_time": datetime.now(timezone.utc).timestamp() + seconds,
        "message_id": giveaway_message.id,
        "guild_id": ctx.guild.id
    }
    log_action("giveaway_start", ctx.author, details=f"Concours '{prize}' pour {duration}")

    await asyncio.sleep(seconds)

    try:
        message = await ctx.channel.fetch_message(giveaway_message.id)
    except discord.NotFound:
        await ctx.send("Erreur : Le message du concours a été supprimé.")
        return
    except Exception:
        await ctx.send("Erreur lors de la récupération du message du concours.")
        return

    users = set()
    for reaction in message.reactions:
        if str(reaction.emoji) == "🎉":
            # await reaction.users().flatten() est déprécié, utilisez la méthode asynchrone
            async for user in reaction.users():
                if user.bot:
                    continue
                users.add(user)

    if not users:
        await ctx.send("😢 Aucun participant pour le concours. Personne n'a gagné.")
        log_action("giveaway_end", ctx.author, details="Aucun participant")
        return

    winner = random.choice(list(users))
    await ctx.send(f"🎊 **Félicitations** {winner.mention} ! Vous avez gagné : **{prize}** 🎉")
    log_action("giveaway_end", ctx.author, winner, details=f"Gagnant : {winner.name}, Prix : {prize}")

# --- Commande de Sondage ---
@bot.command()
async def sondage(ctx, *, question):
    """Crée un sondage simple avec les réactions 👍 et 👎."""
    embed = discord.Embed(
        title="📊 Sondage",
        description=question,
        color=0x00ffff
    )
    embed.set_footer(text=f"Sondage créé par {ctx.author.display_name}")
    embed.timestamp = datetime.now(timezone.utc)
    message = await ctx.send(embed=embed)
    await message.add_reaction("👍")
    await message.add_reaction("👎")
    try:
        await ctx.message.delete() # Supprime le message de commande
    except discord.Forbidden:
        print(f"Avertissement: Impossible de supprimer le message de commande du sondage pour {ctx.author}.")


# --- Vues et Commandes du Système de Tickets ---

# Vue pour la fermeture d'un ticket individuel
class CloseTicketView(View):
    def __init__(self):
        super().__init__(timeout=None) # Garder la vue active indéfiniment

    @discord.ui.button(label="Fermer le ticket", style=discord.ButtonStyle.red, custom_id="close_ticket_button")
    async def close_ticket_button(self, interaction: discord.Interaction, button: Button):
        channel = interaction.channel
        guild = interaction.guild
        user_closing = interaction.user

        # Désactiver le bouton pour éviter les doubles clics pendant le processus
        self.children[0].disabled = True
        await interaction.message.edit(view=self)

        # Vérification des permissions de fermeture (créateur ou admin)
        ticket_creator_id = None
        if channel.name.startswith("ticket-"):
            try:
                # Extraire l'ID du créateur du nom du canal (ex: ticket-123456789)
                ticket_creator_id = int(channel.name.split("-")[1])
            except ValueError:
                print(f"DEBUG: Nom de canal {channel.name} non standard, impossible d'extraire l'ID du créateur.")
                pass # Le nom du canal n'est peut-être pas au format ticket-ID_UTILISATEUR

        # Seul le créateur du ticket ou un administrateur peut fermer
        if ticket_creator_id is not None and user_closing.id != ticket_creator_id and not user_closing.guild_permissions.administrator:
            await interaction.response.send_message("❌ Vous n'avez pas la permission de fermer ce ticket.", ephemeral=True)
            self.children[0].disabled = False # Réactiver le bouton si la permission est refusée
            await interaction.message.edit(view=self)
            return
        elif ticket_creator_id is None and not user_closing.guild_permissions.administrator:
            # Solution de repli si l'ID n'a pas pu être extrait ou nom non standard
            await interaction.response.send_message("❌ Vous n'avez pas la permission de fermer ce ticket.", ephemeral=True)
            self.children[0].disabled = False # Réactiver le bouton si la permission est refusée
            await interaction.message.edit(view=self)
            return
        
        # Répondre à l'interaction en premier, avant les opérations longues
        await interaction.response.send_message("✅ Ticket fermé. Envoi de la retranscription aux administrateurs, puis suppression dans 5 secondes...")
        
        log_action("ticket_close", user_closing, details=f"Ticket fermé : {channel.name} par le bouton")

        # --- Partie GESTION DE LA RETRANSCRIPTION ---
        transcript = f"Retranscription du ticket {channel.name} fermé par {user_closing} le {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} (UTC):\n\n"
        
        try:
            # Récupérer tous les messages du ticket, en ordre chronologique
            messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]
            for msg in messages:
                time_str = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
                transcript += f"[{time_str}] {msg.author.display_name}: {msg.content}\n"
        except Exception as e:
            transcript += f"\n--- ERREUR LORS DE LA RÉCUPÉRATION DES MESSAGES: {e} ---\n"
            print(f"DEBUG: Erreur lors de la récupération des messages pour la retranscription dans {channel.name}: {e}")

        # Envoyer la retranscription à tous les administrateurs
        admin_members_notified = 0
        for member in guild.members:
            # Vérifiez si le membre est un administrateur (ou a 'gérer les messages' comme staff) et n'est pas un bot
            if (member.guild_permissions.administrator or member.guild_permissions.manage_messages) and not member.bot:
                try:
                    # Envoyer sous forme de fichier si la retranscription est trop longue pour un seul message
                    if len(transcript) > 1900: # La limite de message Discord est de 2000 caractères
                        # Créer un fichier temporaire
                        with open("transcript.txt", "w", encoding="utf-8") as f:
                            f.write(transcript)
                        await member.send(f"📄 **Retranscription du ticket pour {channel.name} :**", file=discord.File("transcript.txt"))
                        os.remove("transcript.txt") # Nettoyer le fichier après l'envoi
                    else:
                        await member.send(f"📄 **Retranscription du ticket pour {channel.name} :**\n```\n{transcript}\n```")
                    admin_members_notified += 1
                except discord.Forbidden:
                    print(f"DEBUG: Impossible d'envoyer la retranscription en DM à l'administrateur {member.name} (Discord.Forbidden).")
                except Exception as e:
                    print(f"DEBUG: Échec de l'envoi de la retranscription à {member.name}: {e}")
        
        print(f"DEBUG: Retranscription envoyée à {admin_members_notified} administrateurs pour le ticket {channel.name}.")
        
        # --- Partie SUPPRESSION DU CANAL ---
        await asyncio.sleep(5) # Attendre 5 secondes comme promis

        try:
            await channel.delete(reason=f"Ticket fermé par {user_closing}")
            print(f"DEBUG: Canal {channel.name} supprimé avec succès.")
            self.stop() # Arrêter la vue après la suppression réussie
        except discord.Forbidden:
            print(f"ERREUR CRITIQUE: Le bot n'a PAS les permissions pour supprimer le canal {channel.name} (discord.Forbidden).")
            # Utilisez interaction.followup.send pour envoyer un message de suivi après la première réponse
            await interaction.followup.send(f"❌ **Erreur grave :** Je n'ai PAS les permissions de supprimer ce canal '{channel.name}'. Veuillez vérifier mes rôles et permissions (`Gérer les salons`) sur le serveur ou supprimez-le manuellement.", ephemeral=False)
        except Exception as e:
            print(f"ERREUR INATTENDUE: Une erreur est survenue lors de la suppression du canal {channel.name} : {e}")
            await interaction.followup.send(f"❌ **Erreur inattendue :** Une erreur est survenue lors de la suppression du canal '{channel.name}' : {e}", ephemeral=False)
        self.stop() # Arrêter la vue même si la suppression échoue, pour éviter des interactions fantômes.


# Vue pour le panel de création de tickets
class TicketCreationView(View):
    def __init__(self):
        super().__init__(timeout=None) # La vue du panel doit rester active indéfiniment

    @discord.ui.button(label="➕ Créer un Ticket", style=discord.ButtonStyle.blurple, custom_id="create_ticket_button")
    async def create_ticket_button_callback(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True, thinking=True) # Affiche "Le bot réfléchit..." en mode éphémère

        guild = interaction.guild
        author = interaction.user
        category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
        
        # Vérifier si la catégorie existe, sinon la créer
        if category is None:
            try:
                # Créer la catégorie avec des permissions de base si elle n'existe pas
                category = await guild.create_category(
                    TICKET_CATEGORY_NAME,
                    overwrites={
                        guild.default_role: discord.PermissionOverwrite(read_messages=False)
                    }
                )
                print(f"DEBUG: Catégorie '{TICKET_CATEGORY_NAME}' créée.")
            except discord.Forbidden:
                await interaction.followup.send("❌ Je n'ai pas les permissions pour créer la catégorie de tickets. Veuillez vérifier mes rôles.", ephemeral=True)
                print(f"ERREUR CRITIQUE: Le bot n'a pas les permissions pour créer la catégorie '{TICKET_CATEGORY_NAME}'.")
                return
            except Exception as e:
                await interaction.followup.send(f"❌ Une erreur est survenue lors de la création de la catégorie : {e}", ephemeral=True)
                print(f"ERREUR INATTENDUE: Erreur lors de la création de la catégorie '{TICKET_CATEGORY_NAME}': {e}")
                return

        # Vérifier si l'utilisateur a déjà un ticket ouvert
        existing_channel = discord.utils.get(guild.text_channels, name=f"ticket-{author.id}")
        if existing_channel:
            await interaction.followup.send(f"❌ Vous avez déjà un ticket ouvert : {existing_channel.mention}", ephemeral=True)
            return

        # Définir les permissions pour le nouveau canal de ticket
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False), # @everyone ne voit pas le ticket
            author: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True), # Le créateur voit et peut envoyer
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True), # Le bot voit, envoie, gère le canal
        }
        
        # Ajouter les membres avec la permission 'gérer les messages' (ou administrateur) au ticket
        for member in guild.members:
            if member.guild_permissions.manage_channels or member.guild_permissions.administrator: # Manage_channels inclut la gestion des salons
                overwrites[member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        try:
            channel = await guild.create_text_channel(
                f"ticket-{author.id}", # Nom du canal avec l'ID de l'utilisateur
                category=category,
                overwrites=overwrites
            )
            # Envoyer le message initial dans le ticket avec le bouton de fermeture
            await channel.send(
                f"Bienvenue {author.mention} ! Veuillez décrire votre problème.\nUn membre du personnel vous répondra bientôt.",
                view=CloseTicketView()
            )
            await interaction.followup.send(f"✅ Votre ticket a été créé : {channel.mention}", ephemeral=True)
            log_action("ticket_create", author, details=f"Ticket créé via panel : {channel.name}")

            # Notifier les administrateurs et les modérateurs du nouveau ticket
            notification_msg = f"🆕 Nouveau ticket créé par {author.mention} ({author.id}) : {channel.mention}"
            for member in guild.members:
                if (member.guild_permissions.administrator or member.guild_permissions.manage_channels) and not member.bot:
                    try:
                        await member.send(notification_msg)
                    except discord.Forbidden:
                        print(f"DEBUG: Impossible d'envoyer la notification de nouveau ticket en DM à {member.name} (Discord.Forbidden).")
                    except Exception as e:
                        print(f"DEBUG: Échec de l'envoi de la notification à {member.name}: {e}")
        
        except discord.Forbidden:
            await interaction.followup.send("❌ Je n'ai pas les permissions pour créer le canal de ticket. Veuillez vérifier mes rôles (notamment 'Gérer les salons').", ephemeral=True)
            print(f"ERREUR CRITIQUE: Le bot n'a pas les permissions pour créer le canal de ticket dans la catégorie '{TICKET_CATEGORY_NAME}'.")
        except Exception as e:
            await interaction.followup.send(f"❌ Une erreur est survenue lors de la création du ticket : {e}", ephemeral=True)
            print(f"ERREUR INATTENDUE: Erreur lors de la création du canal de ticket: {e}")

@bot.command(name="ticketpanel")
@is_admin()
async def ticket_panel(ctx):
    """Envoie le panel de création de tickets au salon actuel avec un beau menu."""
    embed = discord.Embed(
        title="🌟 Bienvenue au Centre d'Aide 🌟",
        description=(
            "Cliquez sur le bouton ci-dessous pour **ouvrir un nouveau ticket**.\n"
            "Notre équipe d'assistance est là pour vous aider avec toutes vos questions et problèmes.\n\n"
            "**Pourquoi créer un ticket ?**\n"
            "• Aide technique\n"
            "• Signalement de problèmes\n"
            "• Questions générales\n"
            "• Et bien plus encore !"
        ),
        color=discord.Color.blue() # Une couleur attrayante
    )
    embed.set_thumbnail(url=bot.user.display_avatar.url) # Photo de profil du bot
    # embed.set_image(url="https://i.imgur.com/your_ticket_banner_image.png") # Optionnel: mettez l'URL d'une image de bannière ici
    embed.set_footer(text="Appuyez sur le bouton pour commencer !")

    await ctx.send(embed=embed, view=TicketCreationView())
    try:
        await ctx.message.delete() # Supprimer le message de commande pour la propreté
    except discord.Forbidden:
        print(f"Avertissement: Impossible de supprimer le message de commande !ticketpanel pour {ctx.author}.")
    log_action("ticket_panel_sent", ctx.author, details=f"Panel de tickets envoyé dans {ctx.channel.name}")


@bot.command()
async def ticket(ctx, action=None):
    """Gère les tickets : crée (via le panel) ou les ferme."""
    # Cette partie est maintenue pour le cas où quelqu'un tenterait d'utiliser !ticket close manuellement.
    # La création via !ticket est volontairement désactivée pour forcer l'utilisation du panel.

    if action is None:
        await ctx.send("❌ Pour créer un ticket, veuillez utiliser le panel de tickets dans le salon approprié (`!ticketpanel`).", ephemeral=True)
        return

    elif action.lower() == "close":
        channel = ctx.channel
        guild = ctx.guild
        user_closing = ctx.author # L'utilisateur qui a tapé la commande

        if not channel.name.startswith("ticket-"):
            await ctx.send("❌ Cette commande (`!ticket close`) doit être utilisée dans un canal de ticket.", ephemeral=True)
            return
        
        # Vérification des permissions de fermeture (créateur ou admin)
        ticket_creator_id = None
        if channel.name.startswith("ticket-"):
            try:
                ticket_creator_id = int(channel.name.split("-")[1])
            except ValueError:
                pass # Le nom du canal n'est peut-être pas au format ticket-ID_UTILISATEUR

        if ticket_creator_id is not None and user_closing.id != ticket_creator_id and not user_closing.guild_permissions.administrator:
            await ctx.send("❌ Vous n'avez pas la permission de fermer ce ticket.", ephemeral=True)
            return
        elif ticket_creator_id is None and not user_closing.guild_permissions.administrator:
            await ctx.send("❌ Vous n'avez pas la permission de fermer ce ticket.", ephemeral=True)
            return

        # Confirmer que le message "Ticket fermé..." est envoyé en premier
        await ctx.send("✅ Ticket fermé. Envoi de la retranscription aux administrateurs, puis suppression dans 5 secondes...")
        log_action("ticket_close", user_closing, details=f"Ticket fermé : {channel.name} par la commande")

        # --- Partie GESTION DE LA RETRANSCRIPTION ---
        transcript = f"Retranscription du ticket {channel.name} fermé par {user_closing} le {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} (UTC):\n\n"
        try:
            messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]
            for msg in messages:
                time_str = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
                transcript += f"[{time_str}] {msg.author.display_name}: {msg.content}\n"
        except Exception as e:
            transcript += f"\n--- ERREUR LORS DE LA RÉCUPÉRATION DES MESSAGES: {e} ---\n"
            print(f"DEBUG: Erreur lors de la récupération des messages pour la retranscription dans {channel.name}: {e}")

        admin_members_notified = 0
        for member in guild.members:
            if (member.guild_permissions.administrator or member.guild_permissions.manage_channels) and not member.bot:
                try:
                    if len(transcript) > 1900:
                        with open("transcript.txt", "w", encoding="utf-8") as f:
                            f.write(transcript)
                        await member.send(f"📄 **Retranscription du ticket pour {channel.name} :**", file=discord.File("transcript.txt"))
                        os.remove("transcript.txt")
                    else:
                        await member.send(f"📄 **Retranscription du ticket pour {channel.name} :**\n```\n{transcript}\n```")
                    admin_members_notified += 1
                except discord.Forbidden:
                    print(f"DEBUG: Impossible d'envoyer la retranscription en DM à l'administrateur {member.name} (Discord.Forbidden).")
                except Exception as e:
                    print(f"DEBUG: Échec de l'envoi de la retranscription à {member.name}: {e}")
        
        print(f"DEBUG: Retranscription envoyée à {admin_members_notified} administrateurs pour le ticket {channel.name}.")

        await asyncio.sleep(5)

        try:
            await channel.delete(reason=f"Ticket fermé par {user_closing}")
            print(f"DEBUG: Canal {channel.name} supprimé avec succès.")
        except discord.Forbidden:
            print(f"ERREUR CRITIQUE: Le bot n'a PAS les permissions pour supprimer le canal {channel.name} (discord.Forbidden).")
            await ctx.send(f"❌ **Erreur grave :** Je n'ai PAS les permissions de supprimer ce canal '{channel.name}'. Veuillez vérifier mes rôles et permissions (`Gérer les salons`) sur le serveur ou supprimez-le manuellement.", ephemeral=False)
        except Exception as e:
            print(f"ERREUR INATTENDUE: Une erreur est survenue lors de la suppression du canal {channel.name} : {e}")
            await ctx.send(f"❌ **Erreur inattendue :** Une erreur est survenue lors de la suppression du canal '{channel.name}' : {e}", ephemeral=False)
    else:
        await ctx.send("❌ Utilisation : `!ticket close` ou utilisez le panneau de tickets.", ephemeral=True)

@bot.command()
async def rename(ctx, *, new_name):
    """Renomme le canal de ticket actuel (uniquement pour les canaux de ticket)."""
    channel = ctx.channel
    if not channel.name.startswith("ticket-"):
        await ctx.send("❌ Cette commande doit être utilisée dans un canal de ticket.")
        return

    # Vérifier si l'auteur est le créateur du ticket ou un administrateur
    channel_id_part = channel.name.split("-")[1]
    is_ticket_creator = False
    try:
        if int(channel_id_part) == ctx.author.id:
            is_ticket_creator = True
    except ValueError:
        pass # Pas un nom de ticket standard

    if ctx.author.guild_permissions.administrator or is_ticket_creator:
        try:
            # Remplacer les espaces par des tirets pour les noms de canaux Discord
            cleaned_new_name = new_name.lower().replace(' ', '-')
            # Assurez-vous que le nom est court et ne contient pas de caractères spéciaux
            cleaned_new_name = re.sub(r'[^a-z0-9-]', '', cleaned_new_name)
            if not cleaned_new_name: # Si le nom est vide après nettoyage
                await ctx.send("❌ Nom de ticket invalide après nettoyage. Veuillez utiliser des caractères alphanumériques.")
                return

            await channel.edit(name=f"ticket-{cleaned_new_name}")
            await ctx.send(f"✅ Ticket renommé en : **ticket-{cleaned_new_name}**")
            log_action("ticket_rename", ctx.author, details=f"Ticket renommé en ticket-{cleaned_new_name}")
        except discord.Forbidden:
            await ctx.send(f"❌ Je n'ai pas les permissions pour renommer ce canal. Vérifiez mes rôles (notamment 'Gérer les salons').")
            print(f"ERREUR CRITIQUE: Le bot n'a pas les permissions pour renommer le canal {channel.name}.")
        except Exception as e:
            await ctx.send(f"Erreur lors du renommage : {e}")
            print(f"ERREUR INATTENDUE: Erreur lors du renommage du canal {channel.name}: {e}")
    else:
        await ctx.send("❌ Vous n'avez pas la permission de renommer ce ticket.")

@bot.command()
@commands.has_permissions(manage_messages=True) # Exige la permission 'Gérer les messages'
async def say(ctx, *, message):
    """
    Fait dire au bot un message.
    Nécessite la permission 'Gérer les messages'.
    """
    try:
        await ctx.message.delete() # Supprime le message de commande de l'utilisateur
        await ctx.send(message)    # Envoie le message que l'utilisateur a tapé
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de supprimer votre message ou d'envoyer le mien ici.")
    except Exception as e:
        await ctx.send(f"Une erreur est survenue lors de l'exécution de la commande `say` : {e}")

# --- NOUVELLE COMMANDE : !send ---
@bot.command()
@is_admin() # Seuls les administrateurs peuvent envoyer des messages privés via cette commande
async def send(ctx, member: discord.Member, *, message):
    """
    Envoie un message privé (DM) à un membre spécifique.
    Usage: !send <@membre> <votre message>
    """
    try:
        await member.send(message)
        await ctx.send(f"✅ Message envoyé à **{member.display_name}**.")
        log_action("send_dm", ctx.author, target=member, details=f"Message: {message}")
    except discord.Forbidden:
        await ctx.send(f"❌ Impossible d'envoyer un message privé à **{member.display_name}**. Leurs paramètres de confidentialité peuvent bloquer les DMs du bot.", ephemeral=True)
        print(f"DEBUG: Impossible d'envoyer un DM à {member.name} (Forbidden).")
    except Exception as e:
        await ctx.send(f"❌ Erreur lors de l'envoi du message privé à {member.display_name} : {e}", ephemeral=True)
        print(f"DEBUG: Erreur lors de l'envoi de DM à {member.name}: {e}")
    finally:
        try:
            await ctx.message.delete() # Supprime le message de commande de l'utilisateur pour la propreté
        except discord.Forbidden:
            print(f"Avertissement: Impossible de supprimer le message de commande !send pour {ctx.author}.")


@bot.command()
async def feedback(ctx, *, message):
    """Envoie un message de feedback à tous les administrateurs via DM."""
    embed = discord.Embed(
        title="📝 Nouveau Feedback",
        description=message,
        color=0x3498db
    )
    embed.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
    embed.timestamp = datetime.now(timezone.utc)

    sent, failed = 0, 0
    for member in ctx.guild.members:
        # Envoyer le feedback aux administrateurs ou ceux qui peuvent gérer les canaux (staff général)
        if (member.guild_permissions.administrator or member.guild_permissions.manage_channels) and not member.bot:
            try:
                await member.send(embed=embed)
                sent += 1
            except discord.Forbidden:
                print(f"DEBUG: Impossible d'envoyer le feedback en DM à {member.name} (Forbidden).")
                failed += 1
            except Exception:
                failed += 1

    await ctx.send(f"✅ Feedback envoyé à **{sent}** membre(s) du staff. **{failed}** échec(s).")
    log_action("feedback", ctx.author, details=message)

@bot.command(name="userinfo")
async def userinfo(ctx, member: discord.Member = None):
    """Affiche les informations sur un membre."""
    member = member or ctx.author

    roles = [role.mention for role in member.roles if role != ctx.guild.default_role]
    roles_display = ", ".join(roles) if roles else "Aucun rôle"

    embed = discord.Embed(
        title=f"Informations pour {member.display_name}",
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="🆔 ID", value=member.id, inline=False)
    embed.add_field(name="🗓️ A rejoint le serveur le", value=member.joined_at.strftime('%d/%m/%Y %H:%M'), inline=True)
    embed.add_field(name="📅 Compte créé le", value=member.created_at.strftime('%d/%m/%Y %H:%M'), inline=True)
    embed.add_field(name="🎭 Rôles", value=roles_display, inline=False)
    embed.set_footer(text=f"Demandé par {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)

@bot.command()
@is_admin()
async def banid(ctx, user_id: int, *, reason=None):
    """Bannit un utilisateur par son ID, même s'il n'est pas sur le serveur."""
    try:
        user = await bot.fetch_user(user_id) # Récupère l'objet utilisateur par ID
        await ctx.guild.ban(user, reason=reason)
        await ctx.send(f"🔨 Utilisateur **`{user}`** (ID : `{user_id}`) a été banni.")
        log_action("banid", ctx.author, user, reason)
    except discord.NotFound:
        await ctx.send(f"❌ Utilisateur avec l'ID `{user_id}` introuvable.")
    except discord.Forbidden:
        await ctx.send(f"❌ Je n'ai pas les permissions pour bannir cet utilisateur.")
    except Exception as e:
        await ctx.send(f"Erreur lors du bannissement par ID : {e}")

@bot.command()
@is_admin()
async def kickid(ctx, user_id: int, *, reason=None):
    """Expulse un utilisateur par son ID s'il est sur le serveur."""
    member = ctx.guild.get_member(user_id) # Tente d'obtenir le membre directement
    if member:
        try:
            await member.kick(reason=reason)
            await ctx.send(f"👢 **`{member.display_name}`** (ID : `{user_id}`) a été expulsé.")
            log_action("kickid", ctx.author, member, reason)
        except discord.Forbidden:
            await ctx.send(f"❌ Je n'ai pas les permissions pour expulser cet utilisateur.")
        except Exception as e:
            await ctx.send(f"Erreur lors de l'expulsion par ID : {e}")
    else:
        await ctx.send(f"❌ Utilisateur avec l'ID `{user_id}` introuvable sur ce serveur.")

@bot.command()
@is_admin()
async def unbanid(ctx, user_id: int):
    """Débannit un utilisateur par son ID."""
    banned_users = await ctx.guild.bans()
    for entry in banned_users:
        if entry.user.id == user_id:
            try:
                await ctx.guild.unban(entry.user)
                await ctx.send(f"✅ **`{entry.user.name}#{entry.user.discriminator}`** (ID : `{user_id}`) a été débanni.")
                log_action("unbanid", ctx.author, entry.user)
                return
            except discord.Forbidden:
                await ctx.send(f"❌ Je n'ai pas les permissions pour débannir cet utilisateur.")
                return
            except Exception as e:
                await ctx.send(f"Erreur lors du débannissement par ID : {e}")
                return
    await ctx.send(f"❌ Utilisateur avec l'ID `{user_id}` introuvable dans la liste des bannissements.")

@bot.command()
@is_admin()
async def lock(ctx):
    """Verrouille le canal actuel, empêchant @everyone d'envoyer des messages."""
    try:
        everyone_role = ctx.guild.default_role
        await ctx.channel.set_permissions(everyone_role, send_messages=False)
        await ctx.send("🔒 Canal **verrouillé**. `@everyone` ne peut plus envoyer de messages ici.")
        log_action("channel_lock", ctx.author, target=ctx.channel, details=f"Canal {ctx.channel.name} verrouillé")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas les permissions pour verrouiller ce canal. Vérifiez mes rôles.")
    except Exception as e:
        await ctx.send(f"Erreur lors du verrouillage du canal : {e}")

@bot.command()
@is_admin()
async def unlock(ctx):
    """Déverrouille le canal actuel, permettant à @everyone d'envoyer des messages."""
    try:
        everyone_role = ctx.guild.default_role
        # Réinitialise la permission send_messages à None (hérite de la catégorie/serveur)
        await ctx.channel.set_permissions(everyone_role, send_messages=None)
        await ctx.send("🔓 Canal **déverrouillé**. `@everyone` peut maintenant envoyer des messages ici.")
        log_action("channel_unlock", ctx.author, target=ctx.channel, details=f"Canal {ctx.channel.name} déverrouillé")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas les permissions pour déverrouiller ce canal. Vérifiez mes rôles.")
    except Exception as e:
        await ctx.send(f"Erreur lors du déverrouillage du canal : {e}")

@bot.command()
@is_admin()
async def slowmode(ctx, seconds: int):
    """
    Définit le mode lent pour le canal actuel.
    La durée est en secondes (0 pour désactiver). Max 21600 secondes (6 heures).
    """
    if seconds < 0 or seconds > 21600:
        await ctx.send("❌ La durée du mode lent doit être entre 0 et 21600 secondes (6 heures).")
        return
    try:
        await ctx.channel.edit(slowmode_delay=seconds)
        if seconds == 0:
            await ctx.send("✅ Mode lent **désactivé** pour ce canal.")
            log_action("slowmode_off", ctx.author, target=ctx.channel)
        else:
            await ctx.send(f"✅ Mode lent défini à **{seconds} secondes** pour ce canal.")
            log_action("slowmode_on", ctx.author, target=ctx.channel, duration=f"{seconds}s")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas les permissions pour définir le mode lent dans ce canal. Vérifiez mes rôles.")
    except Exception as e:
        await ctx.send(f"Erreur lors de la définition du mode lent : {e}")

# --- Commandes Anti-Raid ---
@bot.command()
@is_admin()
async def raid(ctx, action: str):
    """
    Active ou désactive le mode anti-raid.
    Usage: !raid on / !raid off
    """
    global anti_raid_enabled

    if action.lower() == "on":
        anti_raid_enabled = True
        await ctx.send("🛡️ Mode anti-raid **activé**. Les comptes récents et les spammers rapides seront bannis.")
        log_action("anti_raid", ctx.author, details="Activé")
    elif action.lower() == "off":
        anti_raid_enabled = False
        await ctx.send("🏳️ Mode anti-raid **désactivé**.")
        log_action("anti_raid", ctx.author, details="Désactivé")
    else:
        await ctx.send("❌ Action invalide. Utilisez `!raid on` ou `!raid off`.")

# --- Commandes Générales Utilitaires ---
@bot.command()
async def ping(ctx):
    """Affiche la latence du bot."""
    await ctx.send(f"🏓 Pong! Latence : **{round(bot.latency * 1000)}ms**")

@bot.command(name="serverinfo")
async def server_info(ctx):
    """Affiche des informations sur le serveur."""
    guild = ctx.guild
    embed = discord.Embed(
        title=f"Informations du serveur **{guild.name}**",
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    embed.add_field(name="🆔 ID du serveur", value=guild.id, inline=True)
    embed.add_field(name="👑 Propriétaire", value=guild.owner.mention, inline=True)
    embed.add_field(name="🗓️ Créé le", value=guild.created_at.strftime('%d/%m/%Y %H:%M'), inline=True)
    embed.add_field(name="👥 Membres", value=guild.member_count, inline=True)
    embed.add_field(name="💬 Salons textuels", value=len(guild.text_channels), inline=True)
    embed.add_field(name="🔊 Salons vocaux", value=len(guild.voice_channels), inline=True)
    embed.add_field(name="🔗 Niveau de Boost", value=f"Niveau {guild.premium_tier} ({guild.premium_subscription_count} boosts)", inline=True)
    
    roles_count = len(guild.roles) - 1 if len(guild.roles) > 0 else 0
    embed.add_field(name="🎭 Rôles", value=roles_count, inline=True)

    await ctx.send(embed=embed)

@bot.command(name="8ball")
async def eight_ball(ctx, *, question: str):
    """Pose une question à la Magic 8 Ball."""
    responses = [
        "Oui, absolument.", "C'est certain.", "Sans aucun doute.", "Oui définitivement.",
        "Tu peux compter dessus.", "Selon mes informations, oui.", "Les perspectives sont bonnes.",
        "Oui.", "Les signes indiquent oui.", "Repose ta question plus tard.",
        "Je ne peux pas te le dire maintenant.", "Je n'ai pas de boule de cristal pour ça.",
        "Concentre-toi et redemande.", "Ne compte pas dessus.", "Ma réponse est non.",
        "Mes sources disent non.", "Les perspectives ne sont pas si bonnes.", "Très douteux."
    ]
    response = random.choice(responses)
    embed = discord.Embed(
        title="🎱 Magic 8 Ball",
        description=f"**Question :** {question}\n**Réponse :** {response}",
        color=discord.Color.purple()
    )
    await ctx.send(embed=embed)

@bot.command()
async def help(ctx):
    """Affiche toutes les commandes disponibles."""
    embed = discord.Embed(
        title="📚 Aide des commandes du bot",
        description="Voici la liste de toutes les commandes disponibles (le préfixe est `!`) :",
        color=discord.Color.blue()
    )

    embed.add_field(name="👮‍♂️ Modération", value="`kick <membre> [raison]`\n`ban <membre> [raison]`\n`unban <nom#tag ou ID>`\n`clear <nombre>`\n`warn <membre> [raison]`\n`unwarn <membre>`\n`mute <membre> [raison]`\n`unmute <membre>`\n`tempmute <membre> <durée> [raison]`\n`lock`\n`unlock`\n`slowmode <secondes>`", inline=False)
    
    embed.add_field(name="🎫 Système de Tickets", value="`ticketpanel` (pour créer le panel)\n`ticket close` (à utiliser dans un ticket)\n`rename <nouveau_nom>` (dans un ticket)", inline=False)
    
    embed.add_field(name="🛠️ Utilitaires", value="`send <@membre> <message>`\n`sendall <message>`\n`giveaway <durée> <prix>`\n`sondage <question>`\n`userinfo [membre]`\n`banid <ID> [raison]`\n`kickid <ID> [raison]`\n`unbanid <ID>`\n`feedback <message>`\n`ping`\n`serverinfo`\n`8ball <question>`\n`say <message>`", inline=False)
    
    embed.add_field(name="🛡️ Anti-Raid", value="`raid on`\n`raid off`", inline=False)

    embed.set_footer(text=f"Préfixe actuel : {PREFIX}")
    await ctx.send(embed=embed)

# --- Événements du Bot ---
@bot.event
async def on_ready():
    print(f'Connecté en tant que {bot.user.name} ({bot.user.id})')
    print('------')
    init_logs()
    init_warns()
    # Ajouter la vue persistante pour le panel de création de tickets
    # Cela permet au bouton du panel de fonctionner même après un redémarrage du bot.
    bot.add_view(TicketCreationView())

@bot.event
async def on_message(message):
    global anti_raid_enabled
    global user_last_message_times

    if message.author.bot:
        await bot.process_commands(message)
        return

    lower_content = message.content.lower()

    # Modération des mots interdits
    if any(word in lower_content for word in bad_words):
        try:
            await message.delete()
            await message.channel.send(f"🚫 {message.author.mention}, votre message contient un mot interdit.", delete_after=5)
            log_action("auto-delete", bot.user, message.author, reason="Mot interdit", details=message.content)
            print(f"DEBUG: Message de {message.author} supprimé (mot interdit).")
        except discord.Forbidden:
            print(f"Avertissement : Le bot n'a pas pu supprimer le message de mot interdit de {message.author} dans {message.channel.name} (permissions manquantes).")
        except Exception as e:
            print(f"Erreur lors de la modération des mots interdits : {e}")

    # Anti-Lien d'invitation Discord
    if "discord.gg/" in lower_content and not message.author.guild_permissions.manage_messages:
        try:
            await message.delete()
            await message.channel.send(f"🚫 {message.author.mention}, les liens d'invitation sont interdits.", delete_after=5)
            log_action("auto-delete", bot.user, message.author, reason="Lien d'invitation interdit", details=message.content)
            print(f"DEBUG: Message de {message.author} supprimé (lien d'invitation).")
        except discord.Forbidden:
            print(f"Avertissement : Le bot n'a pas pu supprimer le lien d'invitation de {message.author} dans {message.channel.name} (permissions manquantes).")
        except Exception as e:
            print(f"Erreur lors de l'anti-lien : {e}")

    # Système Anti-Raid
    if anti_raid_enabled:
        user_id_str = str(message.author.id)
        current_time = datetime.now(timezone.utc)

        # Anti-spam rapide
        if user_id_str in user_last_message_times:
            delta = (current_time - user_last_message_times[user_id_str]).total_seconds()
            if delta < 1: # Si deux messages sont envoyés en moins d'une seconde
                try:
                    await message.delete()
                    await message.channel.send(f"{message.author.mention} : Comportement suspect détecté. Message supprimé.", delete_after=5)
                    await message.author.ban(reason="Raid détecté : spam rapide")
                    log_action("antiraid_ban", bot.user, message.author, "Spam rapide")
                    print(f"DEBUG: {message.author} banni pour spam rapide.")
                    return # Arrête le traitement du message après le ban
                except discord.Forbidden:
                    print(f"Avertissement : Le bot n'a pas pu bannir {message.author} pour spam (permissions manquantes).")
                except Exception as e:
                    print(f"Erreur lors du bannissement anti-spam : {e}")
        user_last_message_times[user_id_str] = current_time

        # Anti-comptes récents
        account_age = (current_time - message.author.created_at).total_seconds()
        if account_age < 600: # Si le compte a moins de 10 minutes (600 secondes)
            try:
                await message.delete()
                await message.channel.send(f"{message.author.mention} : Compte trop récent. Banni pour sécurité.", delete_after=5)
                await message.author.ban(reason="Raid détecté : compte récent")
                log_action("antiraid_ban", bot.user, message.author, "Compte trop récent")
                print(f"DEBUG: {message.author} banni pour compte trop récent.")
                return # Arrête le traitement du message après le ban
            except discord.Forbidden:
                print(f"Avertissement : Le bot n'a pas pu bannir {message.author} pour compte récent (permissions manquantes).")
            except Exception as e:
                print(f"Erreur lors du bannissement de compte récent : {e}")

    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    # La permission 'Gérer les messages' est ajoutée ici pour plus de précision sur les erreurs CheckFailure
    if isinstance(error, commands.CommandNotFound):
        pass # Ignore les commandes introuvables (pour ne pas spammer le chat)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Argument(s) manquant(s). Utilisation correcte : `{PREFIX}{ctx.command.name} {ctx.command.signature}`", ephemeral=True)
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Argument(s) invalide(s). Veuillez vérifier le type d'argument attendu.", ephemeral=True)
    elif isinstance(error, commands.CheckFailure):
        # Si c'est une erreur de permission spécifique (ex: has_permissions)
        if isinstance(error, commands.MissingPermissions):
            perms_needed = ", ".join(error.missing_permissions)
            await ctx.send(f"🚫 Vous n'avez pas les permissions nécessaires pour cette commande : `{perms_needed}`.", ephemeral=True)
        elif isinstance(error, commands.NotOwner):
             await ctx.send("🚫 Seul le propriétaire du bot peut utiliser cette commande.", ephemeral=True)
        else: 
             await ctx.send("🚫 Vous n'avez pas la permission d'utiliser cette commande.", ephemeral=True)
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Le memebre saisie est invalide verifier L'identifiant !", ephemeral=True)
    elif isinstance(error, discord.Forbidden):
        await ctx.send("🚫 DIDI N'as pas la permitiondefaire cela !", ephemeral=False) 
    else:
        print(f"Ignorer l'exception dans la commande {ctx.command} :", error)
        await ctx.send(f"Une erreur inattendue est survenue : {error}", ephemeral=True)
        log_action("command_error", bot.user, ctx.author, details=str(error))

# --- Exécuter le bot ---
if TOKEN is None:
    print("Erreur : Vous devez entrer votre token dans le fichier .env !")
else:
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("Erreur de connexion : Verifier le token present dans le fichier .env !.")
    except Exception as e:
        print(f"Une erreur inattendue est survenue au démarrage du bot : {e}")
