"""Small, dependency-free translations for Legion Control's user interface.

The application is distributed as plain Python files, including its Debian
package.  Keeping the catalog in this module makes translations available in
both development and packaged builds without relying on a system ``msgfmt``
step.  Spanish remains the source language; unknown strings intentionally
fall back to it instead of failing or showing a message identifier.
"""

from __future__ import annotations

import json
import locale
import os
from pathlib import Path
from typing import Final


LANGUAGES: Final = ("en", "es", "fr", "zh", "ru")
LANGUAGE_NAMES: Final = {
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "zh": "中文",
    "ru": "Русский",
}
DEFAULT_LANGUAGE: Final = "en"
# Library callers that do not initialize the application preserve its historic
# Spanish output.  GUI and CLI entry points always call configure_startup_language.
_ACTIVE_LANGUAGE = "es"


def _catalog(entries: tuple[tuple[str, str, str, str, str], ...], index: int) -> dict[str, str]:
    return {spanish: entry[index] for spanish, *entry in entries}


# Source text, English, French, Simplified Chinese, Russian.  Keep variables in
# source strings (``{count}``, ``{label}``, etc.) so every language can format
# dynamic status messages correctly.
_ENTRIES: Final = (
    ("Inicio", "Home", "Accueil", "主页", "Главная"),
    ("Ventilación", "Fans", "Ventilation", "风扇", "Вентиляторы"),
    ("Iluminación", "Lighting", "Éclairage", "灯光", "Подсветка"),
    ("Dispositivo", "Device", "Appareil", "设备", "Устройство"),
    ("Automatización", "Automation", "Automatisation", "自动化", "Автоматизация"),
    ("Idioma", "Language", "Langue", "语言", "Язык"),
    ("Doctor", "Doctor", "Diagnostic", "诊断", "Диагностика"),
    ("Estado térmico", "Thermal status", "État thermique", "温度状态", "Тепловой статус"),
    (
        "Lecturas actuales del equipo",
        "Current device readings",
        "Mesures actuelles de l’appareil",
        "设备当前读数",
        "Текущие показания устройства",
    ),
    ("Estado estable", "Stable", "État stable", "状态稳定", "Стабильно"),
    (
        "Lecturas incompletas",
        "Incomplete readings",
        "Mesures incomplètes",
        "读数不完整",
        "Неполные показания",
    ),
    (
        "Temperatura crítica",
        "Critical temperature",
        "Température critique",
        "温度严重",
        "Критическая температура",
    ),
    (
        "Temperatura elevada",
        "High temperature",
        "Température élevée",
        "温度过高",
        "Высокая температура",
    ),
    ("MÁS CALIENTE", "HOTTEST", "PLUS CHAUD", "最高温度", "САМАЯ ВЫСОКАЯ"),
    ("VENTILADOR 1", "FAN 1", "VENTILATEUR 1", "风扇 1", "ВЕНТИЛЯТОР 1"),
    ("VENTILADOR 2", "FAN 2", "VENTILATEUR 2", "风扇 2", "ВЕНТИЛЯТОР 2"),
    ("OBJETIVO", "TARGET", "CIBLE", "目标", "ЦЕЛЬ"),
    ("Rendimiento", "Performance", "Performances", "性能", "Производительность"),
    (
        "Ruido, consumo y potencia · se aplica al instante",
        "Noise, power use and performance · applied instantly",
        "Bruit, consommation et puissance · appliqué immédiatement",
        "噪音、功耗和性能 · 立即生效",
        "Шум, энергопотребление и мощность · применяется сразу",
    ),
    ("Perfil térmico", "Thermal profile", "Profil thermique", "温控模式", "Тепловой профиль"),
    (
        "Esperando lectura del kernel",
        "Waiting for kernel reading",
        "En attente d’une mesure du noyau",
        "等待内核读数",
        "Ожидание данных ядра",
    ),
    ("Resumen", "Summary", "Résumé", "摘要", "Сводка"),
    ("Batería", "Battery", "Batterie", "电池", "Батарея"),
    ("Control de curva", "Curve control", "Contrôle de courbe", "曲线控制", "Управление кривой"),
    (
        "Servicio térmico local",
        "Local thermal service",
        "Service thermique local",
        "本地温控服务",
        "Локальная тепловая служба",
    ),
    ("Activo", "Active", "Actif", "已启用", "Активно"),
    ("No disponible", "Unavailable", "Indisponible", "不可用", "Недоступно"),
    ("Perfil desconocido", "Unknown profile", "Profil inconnu", "未知模式", "Неизвестный профиль"),
    ("Curva activa", "Curve active", "Courbe active", "曲线已启用", "Кривая активна"),
    (
        "Control firmware",
        "Firmware control",
        "Contrôle du firmware",
        "固件控制",
        "Управление прошивкой",
    ),
    (
        "Confirmado por el kernel: {profile}",
        "Confirmed by kernel: {profile}",
        "Confirmé par le noyau : {profile}",
        "内核已确认：{profile}",
        "Подтверждено ядром: {profile}",
    ),
    (
        "Confirmando {profile}…",
        "Confirming {profile}…",
        "Confirmation de {profile}…",
        "正在确认 {profile}…",
        "Подтверждение {profile}…",
    ),
    (
        "Perfil cambiado a {profile}.",
        "Profile changed to {profile}.",
        "Profil remplacé par {profile}.",
        "已切换到 {profile}。",
        "Профиль изменён на {profile}.",
    ),
    ("Silencioso", "Quiet", "Silencieux", "静音", "Тихий"),
    ("Equilibrado", "Balanced", "Équilibré", "均衡", "Сбалансированный"),
    (
        "Rendimiento máximo",
        "Maximum performance",
        "Performances maximales",
        "最高性能",
        "Максимальная производительность",
    ),
    ("Personalizado", "Custom", "Personnalisé", "自定义", "Пользовательский"),
    ("Automático", "Automatic", "Automatique", "自动", "Автоматический"),
    ("RPM fija", "Fixed RPM", "RPM fixe", "固定转速", "Фиксированные об/мин"),
    ("Curva", "Curve", "Courbe", "曲线", "Кривая"),
    (
        "Salida segura: control firmware",
        "Safe exit: firmware control",
        "Sortie sûre : contrôle du firmware",
        "安全退出：固件控制",
        "Безопасный выход: управление прошивкой",
    ),
    (
        "Detiene el servicio y devuelve ambos objetivos a automático",
        "Stops the service and returns both targets to automatic",
        "Arrête le service et remet les deux cibles en automatique",
        "停止服务并将两个目标恢复为自动",
        "Останавливает службу и возвращает обе цели в автоматический режим",
    ),
    (
        "Recuperación segura",
        "Safe recovery",
        "Récupération sûre",
        "安全恢复",
        "Безопасное восстановление",
    ),
    (
        "Restaurar firmware",
        "Restore firmware",
        "Restaurer le firmware",
        "恢复固件控制",
        "Восстановить прошивку",
    ),
    (
        "Potencia personalizada",
        "Custom power",
        "Puissance personnalisée",
        "自定义功耗",
        "Пользовательская мощность",
    ),
    (
        "Se aplica junto con la ventilación al pulsar Aplicar",
        "Applied together with the fans when you press Apply",
        "Appliquée avec les ventilateurs lorsque vous cliquez sur Appliquer",
        "点击应用时与风扇一起生效",
        "Применяется вместе с вентиляторами по нажатию «Применить»",
    ),
    (
        "Potencia sostenida",
        "Sustained power",
        "Puissance soutenue",
        "持续功耗",
        "Длительная мощность",
    ),
    (
        "Vatios que la CPU puede mantener sin parar · PPT PL1",
        "Watts the CPU can sustain indefinitely · PPT PL1",
        "Watts que le CPU peut tenir en continu · PPT PL1",
        "CPU 可长期维持的瓦数 · PPT PL1",
        "Ватты, которые CPU держит постоянно · PPT PL1",
    ),
    ("Potencia lenta", "Slow power", "Puissance lente", "短时功耗", "Кратковременная мощность"),
    (
        "Vatios de pico en ráfagas cortas · PPT PL2",
        "Peak watts during short bursts · PPT PL2",
        "Watts de pointe lors de courtes rafales · PPT PL2",
        "短时爆发的峰值瓦数 · PPT PL2",
        "Пиковые ватты на коротких всплесках · PPT PL2",
    ),
    ("Modo de ventilación", "Fan mode", "Mode ventilateur", "风扇模式", "Режим вентилятора"),
    (
        "Se aplica al pulsar Aplicar · la curva continúa aunque cierres la ventana",
        "Applied when you press Apply · the curve continues after you close the window",
        "Appliqué en cliquant sur Appliquer · la courbe continue après fermeture",
        "点击应用时生效 · 关闭窗口后曲线仍继续运行",
        "Применяется по нажатию «Применить» · кривая работает после закрытия окна",
    ),
    (
        "Cambios sin aplicar · pulsa Aplicar para activarlos",
        "Unapplied changes · press Apply to activate them",
        "Modifications non appliquées · cliquez sur Appliquer pour les activer",
        "更改尚未应用 · 点击应用以启用",
        "Изменения не применены · нажмите «Применить»",
    ),
    ("Aplicar curva", "Apply curve", "Appliquer la courbe", "应用曲线", "Применить кривую"),
    (
        "El firmware decide la velocidad. Es el estado más seguro si no necesitas una curva propia.",
        "Firmware chooses the speed. This is the safest state when you do not need your own curve.",
        "Le firmware choisit la vitesse. C’est l’état le plus sûr si vous n’avez pas besoin de votre propre courbe.",
        "固件决定速度。若不需要自定义曲线，这是最安全的状态。",
        "Прошивка выбирает скорость. Это самый безопасный режим, если собственная кривая не нужна.",
    ),
    ("Temperatura", "Temperature", "Température", "温度", "Температура"),
    ("Objetivo", "Target", "Cible", "目标", "Цель"),
    ("Punto {index}", "Point {index}", "Point {index}", "点 {index}", "Точка {index}"),
    (
        "Curva de temperatura y RPM con el punto de trabajo actual",
        "Temperature/RPM curve with current operating point",
        "Courbe température/RPM avec le point de fonctionnement actuel",
        "显示当前工作点的温度/转速曲线",
        "Кривая температуры/об/мин с текущей рабочей точкой",
    ),
    (
        "Usar control automático",
        "Use automatic control",
        "Utiliser le contrôle automatique",
        "使用自动控制",
        "Использовать автоматическое управление",
    ),
    (
        "Aplicar RPM + potencia",
        "Apply RPM + power",
        "Appliquer RPM + puissance",
        "应用转速 + 功耗",
        "Применить об/мин + мощность",
    ),
    (
        "Aplicar curva + potencia",
        "Apply curve + power",
        "Appliquer courbe + puissance",
        "应用曲线 + 功耗",
        "Применить кривую + мощность",
    ),
    (
        "Control devuelto al firmware.",
        "Control returned to firmware.",
        "Contrôle rendu au firmware.",
        "控制已交还给固件。",
        "Управление возвращено прошивке.",
    ),
    (
        "Configuración de ventilación aplicada.",
        "Fan configuration applied.",
        "Configuration des ventilateurs appliquée.",
        "风扇配置已应用。",
        "Конфигурация вентиляторов применена.",
    ),
    (
        "Funciones del equipo",
        "Device features",
        "Fonctions de l’appareil",
        "设备功能",
        "Функции устройства",
    ),
    (
        "Se aplican al instante y las guarda el firmware",
        "Applied instantly and saved by the firmware",
        "Appliqués immédiatement et enregistrés par le firmware",
        "立即生效并由固件保存",
        "Применяются сразу и сохраняются прошивкой",
    ),
    (
        "Detectando modelo…",
        "Detecting model…",
        "Détection du modèle…",
        "正在检测型号…",
        "Определение модели…",
    ),
    ("Compatible", "Supported", "Compatible", "支持", "Поддерживается"),
    ("Solo lectura", "Read-only", "Lecture seule", "只读", "Только чтение"),
    (
        "Función actualizada.",
        "Feature updated.",
        "Fonction mise à jour.",
        "功能已更新。",
        "Функция обновлена.",
    ),
    ("Aplicando", "Applying", "Application", "正在应用", "Применение"),
    (
        "Aplicando cambio",
        "Applying change",
        "Application de la modification",
        "正在应用更改",
        "Применение изменения",
    ),
    (
        "Espera a que termine el cambio en curso.",
        "Wait for the current change to finish.",
        "Attendez la fin de la modification en cours.",
        "请等待当前更改完成。",
        "Дождитесь завершения текущего изменения.",
    ),
    (
        "Modelo {product} no admitido: controles bloqueados",
        "Model {product} is unsupported: controls locked",
        "Modèle {product} non pris en charge : contrôles verrouillés",
        "不支持型号 {product}：控制已锁定",
        "Модель {product} не поддерживается: элементы управления заблокированы",
    ),
    (
        "El kernel no publica control manual de ventiladores",
        "Kernel does not expose manual fan control",
        "Le noyau n’expose pas le contrôle manuel des ventilateurs",
        "内核未提供手动风扇控制",
        "Ядро не предоставляет ручное управление вентиляторами",
    ),
    (
        "No se puede leer el equipo: {message}",
        "Cannot read device: {message}",
        "Impossible de lire l’appareil : {message}",
        "无法读取设备：{message}",
        "Не удалось прочитать устройство: {message}",
    ),
    (
        "No se aplicó la automatización: {error}",
        "Automation was not applied: {error}",
        "L’automatisation n’a pas été appliquée : {error}",
        "自动化未应用：{error}",
        "Автоматизация не применена: {error}",
    ),
    (
        "Automatización: escena {scene} aplicada.",
        "Automation: {scene} scene applied.",
        "Automatisation : scène {scene} appliquée.",
        "自动化：已应用 {scene} 场景。",
        "Автоматизация: применена сцена {scene}.",
    ),
    ("Escenas rápidas", "Quick scenes", "Scènes rapides", "快速场景", "Быстрые сцены"),
    (
        "Perfil, ventilación, potencia y RGB con una acción",
        "Profile, fans, power and RGB in one action",
        "Profil, ventilateurs, puissance et RGB en une action",
        "一键设置模式、风扇、功耗和 RGB",
        "Профиль, вентиляторы, мощность и RGB одним действием",
    ),
    ("Silencio", "Quiet", "Silence", "静音", "Тишина"),
    ("Trabajo", "Work", "Travail", "办公", "Работа"),
    ("Juego", "Gaming", "Jeu", "游戏", "Игра"),
    (
        "Preparando escena…",
        "Preparing scene…",
        "Préparation de la scène…",
        "正在准备场景…",
        "Подготовка сцены…",
    ),
    (
        "Guardar estado actual en {scene}",
        "Save current state to {scene}",
        "Enregistrer l’état actuel dans {scene}",
        "将当前状态保存到 {scene}",
        "Сохранить текущее состояние в «{scene}»",
    ),
    ("Aplicar", "Apply", "Appliquer", "应用", "Применить"),
    (
        "Escena {scene} aplicada.",
        "{scene} scene applied.",
        "Scène {scene} appliquée.",
        "已应用 {scene} 场景。",
        "Сцена «{scene}» применена.",
    ),
    (
        "Estado actual guardado en {scene}.",
        "Current state saved to {scene}.",
        "État actuel enregistré dans {scene}.",
        "当前状态已保存到 {scene}。",
        "Текущее состояние сохранено в «{scene}».",
    ),
    ("RGB apagado", "RGB off", "RGB éteint", "RGB 已关闭", "RGB выключен"),
    (
        "Teclado RGB · 24 zonas",
        "RGB keyboard · 24 zones",
        "Clavier RGB · 24 zones",
        "RGB 键盘 · 24 个区域",
        "RGB-клавиатура · 24 зоны",
    ),
    (
        "Detectando controlador HID…",
        "Detecting HID controller…",
        "Détection du contrôleur HID…",
        "正在检测 HID 控制器…",
        "Определение HID-контроллера…",
    ),
    ("Detectando", "Detecting", "Détection", "正在检测", "Определение"),
    ("Control", "Control", "Contrôle", "控制", "Управление"),
    (
        "Se aplica al pulsar Aplicar · un solo cambio para las 24 zonas",
        "Applied when you press Apply · one change for all 24 zones",
        "Appliqué en cliquant sur Appliquer · une seule modification pour les 24 zones",
        "点击应用时生效 · 24 个区域一次性更改",
        "Применяется по нажатию «Применить» · одно изменение для всех 24 зон",
    ),
    (
        "Apaga sin perder colores guardados",
        "Turns off without losing saved colours",
        "Éteint sans perdre les couleurs enregistrées",
        "关闭但不丢失已保存的颜色",
        "Выключает, не теряя сохранённые цвета",
    ),
    ("Brillo", "Brightness", "Luminosité", "亮度", "Яркость"),
    ("Color de zona", "Zone colour", "Couleur de zone", "区域颜色", "Цвет зоны"),
    (
        "Selecciona una zona o aplica el color a todas",
        "Select a zone or apply its colour to all",
        "Sélectionnez une zone ou appliquez sa couleur à toutes",
        "选择一个区域或将颜色应用到全部",
        "Выберите зону или примените её цвет ко всем",
    ),
    ("Aplicar a todas", "Apply to all", "Appliquer à toutes", "应用到全部", "Применить ко всем"),
    ("Zonas", "Zones", "Zones", "区域", "Зоны"),
    (
        "Selecciona una de las 24 zonas y cambia su color",
        "Select one of the 24 zones and change its colour",
        "Sélectionnez une des 24 zones et changez sa couleur",
        "选择 24 个区域之一并更改其颜色",
        "Выберите одну из 24 зон и измените её цвет",
    ),
    (
        "Presets y efectos estáticos",
        "Presets and static effects",
        "Préréglages et effets statiques",
        "预设和静态效果",
        "Предустановки и статические эффекты",
    ),
    (
        "Un solo frame verificado; no activa animaciones de firmware no comprobadas",
        "One verified frame; does not enable unverified firmware animations",
        "Une seule image vérifiée ; n’active pas les animations du firmware non vérifiées",
        "单个已验证帧；不启用未经验证的固件动画",
        "Один проверенный кадр; не включает непроверенную анимацию прошивки",
    ),
    ("Blanco", "White", "Blanc", "白色", "Белый"),
    ("Espectro", "Spectrum", "Spectre", "光谱", "Спектр"),
    ("Atardecer", "Sunset", "Coucher de soleil", "日落", "Закат"),
    ("Ola", "Wave", "Vague", "波浪", "Волна"),
    ("Apagar", "Turn off", "Éteindre", "关闭", "Выключить"),
    (
        "Aplicar iluminación",
        "Apply lighting",
        "Appliquer l’éclairage",
        "应用灯光",
        "Применить подсветку",
    ),
    (
        "No aparece 048d:c195 en la interfaz HID esperada",
        "048d:c195 is not present on the expected HID interface",
        "048d:c195 n’est pas présent sur l’interface HID attendue",
        "预期的 HID 接口中未出现 048d:c195",
        "048d:c195 отсутствует в ожидаемом HID-интерфейсе",
    ),
    ("Aplicado", "Applied", "Appliqué", "已应用", "Применено"),
    (
        "Configuración confirmada por el helper local",
        "Configuration confirmed by local helper",
        "Configuration confirmée par l’assistant local",
        "配置已由本地助手确认",
        "Конфигурация подтверждена локальным помощником",
    ),
    ("Detectado", "Detected", "Détecté", "已检测到", "Обнаружено"),
    (
        "Controlador listo · aplica un preset para sincronizar",
        "Controller ready · apply a preset to sync",
        "Contrôleur prêt · appliquez un préréglage pour synchroniser",
        "控制器已就绪 · 应用预设以同步",
        "Контроллер готов · примените предустановку для синхронизации",
    ),
    (
        "Editar zona {index}",
        "Edit zone {index}",
        "Modifier la zone {index}",
        "编辑区域 {index}",
        "Изменить зону {index}",
    ),
    (
        "Zona RGB {index}",
        "RGB zone {index}",
        "Zone RGB {index}",
        "RGB 区域 {index}",
        "Зона RGB {index}",
    ),
    (
        "Iluminación aplicada en las 24 zonas.",
        "Lighting applied to all 24 zones.",
        "Éclairage appliqué aux 24 zones.",
        "灯光已应用到全部 24 个区域。",
        "Подсветка применена ко всем 24 зонам.",
    ),
    (
        "Últimos 10 minutos",
        "Last 10 minutes",
        "10 dernières minutes",
        "最近 10 分钟",
        "Последние 10 минут",
    ),
    (
        "Recopilando lecturas…",
        "Collecting readings…",
        "Collecte des mesures…",
        "正在收集读数…",
        "Сбор показаний…",
    ),
    ("Fan 1", "Fan 1", "Ventilateur 1", "风扇 1", "Вентилятор 1"),
    ("Fan 2", "Fan 2", "Ventilateur 2", "风扇 2", "Вентилятор 2"),
    ("Exportar CSV", "Export CSV", "Exporter CSV", "导出 CSV", "Экспорт CSV"),
    (
        "Historial de temperaturas CPU/GPU y RPM de ambos ventiladores",
        "CPU/GPU temperature and both fan RPM history",
        "Historique des températures CPU/GPU et des RPM des deux ventilateurs",
        "CPU/GPU 温度和两个风扇转速历史",
        "История температур CPU/GPU и оборотов обоих вентиляторов",
    ),
    (
        "{count} lecturas · guardado local durante 7 días · vista {label}",
        "{count} readings · stored locally for 7 days · {label} view",
        "{count} mesures · conservées localement 7 jours · vue {label}",
        "{count} 个读数 · 本地保存 7 天 · {label} 视图",
        "{count} показаний · хранится локально 7 дней · вид {label}",
    ),
    (
        "Historial · {label}",
        "History · {label}",
        "Historique · {label}",
        "历史 · {label}",
        "История · {label}",
    ),
    (
        "{count} lecturas · guardado local durante 7 días",
        "{count} readings · stored locally for 7 days",
        "{count} mesures · conservées localement 7 jours",
        "{count} 个读数 · 本地保存 7 天",
        "{count} показаний · хранится локально 7 дней",
    ),
    (
        "Exportar historial térmico",
        "Export thermal history",
        "Exporter l’historique thermique",
        "导出温度历史",
        "Экспорт истории температур",
    ),
    ("Exportar", "Export", "Exporter", "导出", "Экспорт"),
    ("Cancelar", "Cancel", "Annuler", "取消", "Отмена"),
    (
        "Historial CSV exportado.",
        "CSV history exported.",
        "Historique CSV exporté.",
        "CSV 历史已导出。",
        "История CSV экспортирована.",
    ),
    (
        "El gráfico aparecerá tras dos lecturas",
        "Chart appears after two readings",
        "Le graphique apparaîtra après deux mesures",
        "图表将在两次读数后显示",
        "График появится после двух показаний",
    ),
    ("Estado de energía", "Power status", "État d’alimentation", "电源状态", "Состояние питания"),
    ("Fuente actual", "Current source", "Source actuelle", "当前电源", "Текущий источник"),
    (
        "Esperando lectura",
        "Waiting for reading",
        "En attente d’une mesure",
        "等待读数",
        "Ожидание показаний",
    ),
    (
        "Escenas al cambiar fuente",
        "Scenes on power-source change",
        "Scènes au changement de source",
        "电源切换时的场景",
        "Сцены при смене источника питания",
    ),
    (
        "Desactivado por defecto · se guarda al instante y actúa con la app abierta",
        "Off by default · saved instantly, acts while the app is open",
        "Désactivé par défaut · enregistré immédiatement, agit si l’app est ouverte",
        "默认关闭 · 立即保存，应用打开时生效",
        "Отключено по умолчанию · сохраняется сразу, работает при открытом приложении",
    ),
    (
        "Al conectar corriente",
        "When AC is connected",
        "Lors du branchement secteur",
        "连接电源时",
        "При подключении питания",
    ),
    (
        "Aplica una escena guardada tras el cambio",
        "Applies a saved scene after the change",
        "Applique une scène enregistrée après le changement",
        "切换后应用已保存的场景",
        "Применяет сохранённую сцену после изменения",
    ),
    ("Escena con corriente", "Scene on AC", "Scène sur secteur", "接通电源场景", "Сцена от сети"),
    (
        "Al usar batería",
        "When using battery",
        "Lors de l’utilisation sur batterie",
        "使用电池时",
        "При работе от батареи",
    ),
    (
        "Escena con batería",
        "Scene on battery",
        "Scène sur batterie",
        "电池供电场景",
        "Сцена от батареи",
    ),
    ("Corriente", "AC power", "Secteur", "交流电源", "Сеть"),
    (
        "Automatización guardada.",
        "Automation saved.",
        "Automatisation enregistrée.",
        "自动化已保存。",
        "Автоматизация сохранена.",
    ),
    (
        "Diagnóstico solo lectura",
        "Read-only diagnostics",
        "Diagnostic en lecture seule",
        "只读诊断",
        "Диагностика только для чтения",
    ),
    (
        "No solicita permisos ni modifica ventiladores, potencia o RGB",
        "Does not request privileges or modify fans, power or RGB",
        "Ne demande aucun privilège et ne modifie ni ventilateurs, puissance ni RGB",
        "不请求权限，也不修改风扇、功耗或 RGB",
        "Не запрашивает привилегии и не изменяет вентиляторы, мощность или RGB",
    ),
    (
        "Esperando lecturas",
        "Waiting for readings",
        "En attente de mesures",
        "等待读数",
        "Ожидание показаний",
    ),
    ("Informe", "Report", "Rapport", "报告", "Отчёт"),
    (
        "Informe solo lectura.",
        "Read-only report.",
        "Rapport en lecture seule.",
        "只读报告。",
        "Отчёт только для чтения.",
    ),
    ("Equipo", "Device", "Appareil", "设备", "Устройство"),
    ("Producto", "Product", "Produit", "产品", "Продукт"),
    ("producto", "product", "produit", "产品", "продукт"),
    ("modelo desconocido", "unknown model", "modèle inconnu", "未知型号", "неизвестная модель"),
    (
        "Control de ventilación",
        "Fan control",
        "Contrôle des ventilateurs",
        "风扇控制",
        "Управление вентиляторами",
    ),
    ("Teclado RGB", "RGB keyboard", "Clavier RGB", "RGB 键盘", "RGB-клавиатура"),
    (
        "Lecturas térmicas",
        "Thermal readings",
        "Mesures thermiques",
        "温度读数",
        "Тепловые показания",
    ),
    ("Servicio de curva", "Curve service", "Service de courbe", "曲线服务", "Служба кривой"),
    ("activo", "active", "actif", "已启用", "активно"),
    # Doctor: environment checks and the remedy attached to each finding.
    (
        "Módulos del kernel",
        "Kernel modules",
        "Modules du noyau",
        "内核模块",
        "Модули ядра",
    ),
    ("Autorización", "Authorization", "Autorisation", "授权", "Авторизация"),
    (
        "Conflicto de perfil",
        "Profile conflict",
        "Conflit de profil",
        "配置文件冲突",
        "Конфликт профиля",
    ),
    ("Conflicto RGB", "RGB conflict", "Conflit RGB", "RGB 冲突", "Конфликт RGB"),
    ("ninguno", "none", "aucun", "无", "нет"),
    ("fallido", "failed", "en échec", "失败", "сбой"),
    ("no legible", "unreadable", "illisible", "无法读取", "не читается"),
    (
        "estado no legible",
        "state unreadable",
        "état illisible",
        "状态无法读取",
        "состояние не читается",
    ),
    (
        "faltan {names}",
        "missing {names}",
        "manque {names}",
        "缺少 {names}",
        "отсутствует {names}",
    ),
    (
        "falta {names}",
        "missing {names}: install required",
        "absent : {names}",
        "缺失 {names}",
        "не найдено {names}",
    ),
    (
        "helper y acción PolicyKit instalados",
        "helper and PolicyKit action installed",
        "assistant et action PolicyKit installés",
        "已安装 helper 与 PolicyKit 动作",
        "helper и действие PolicyKit установлены",
    ),
    (
        "{version} · validada {expected}",
        "{version} · validated {expected}",
        "{version} · validée {expected}",
        "{version} · 已验证 {expected}",
        "{version} · проверена {expected}",
    ),
    ("Volver a comprobar", "Check again", "Vérifier à nouveau", "重新检查", "Проверить снова"),
    (
        "Comprobaciones actualizadas.",
        "Checks refreshed.",
        "Vérifications actualisées.",
        "检查已刷新。",
        "Проверки обновлены.",
    ),
    (
        "Informe Doctor copiado en JSON.",
        "Doctor report copied as JSON.",
        "Rapport Doctor copié en JSON.",
        "诊断报告已复制为 JSON。",
        "Отчёт диагностики скопирован в JSON.",
    ),
    (
        "No se pudo inspeccionar el sistema: {error}",
        "The system could not be inspected: {error}",
        "Impossible d’inspecter le système : {error}",
        "无法检查系统：{error}",
        "Не удалось проверить систему: {error}",
    ),
    (
        "Este equipo no está en la lista de modelos verificados.",
        "This machine is not on the verified model list.",
        "Cet appareil ne figure pas dans la liste des modèles vérifiés.",
        "本机不在已验证机型列表中。",
        "Это устройство отсутствует в списке проверенных моделей.",
    ),
    (
        "El kernel no publica fan1_target; solo queda el control del firmware.",
        "The kernel does not expose fan1_target; only firmware control remains.",
        "Le noyau n’expose pas fan1_target ; seul le contrôle du firmware reste.",
        "内核未提供 fan1_target，仅剩固件控制。",
        "Ядро не предоставляет fan1_target; остаётся только управление прошивкой.",
    ),
    (
        "No aparece el nodo hidraw de 048d:c195. Reconecta o revisa el modelo.",
        "No hidraw node for 048d:c195. Reconnect it or check the model.",
        "Aucun nœud hidraw pour 048d:c195. Reconnectez-le ou vérifiez le modèle.",
        "未找到 048d:c195 的 hidraw 节点。请重新连接或检查机型。",
        "Нет узла hidraw для 048d:c195. Переподключите или проверьте модель.",
    ),
    (
        "Sin la versión de BIOS no se puede comparar con la validada.",
        "Without the BIOS version there is nothing to compare with the validated one.",
        "Sans la version du BIOS, aucune comparaison avec celle validée n’est possible.",
        "没有 BIOS 版本就无法与已验证版本比较。",
        "Без версии BIOS сравнить её с проверенной невозможно.",
    ),
    (
        "Otra BIOS puede mover los límites publicados. Revisa antes de escribir.",
        "Another BIOS may move the published limits. Check before writing.",
        "Un autre BIOS peut déplacer les limites publiées. Vérifiez avant d’écrire.",
        "其他 BIOS 可能改变已公布的限值。写入前请先确认。",
        "Другая BIOS может изменить опубликованные пределы. Проверьте перед записью.",
    ),
    (
        "Sin los módulos WMI de Lenovo no hay perfil, ventilación ni potencia.",
        "Without the Lenovo WMI modules there is no profile, fan or power control.",
        "Sans les modules WMI Lenovo, ni profil, ni ventilation, ni puissance.",
        "缺少 Lenovo WMI 模块则没有配置文件、风扇与功耗控制。",
        "Без модулей Lenovo WMI нет профиля, вентиляторов и мощности.",
    ),
    (
        "Instala el paquete: sin esos archivos ningún cambio llega al hardware.",
        "Install the package: without those files no change reaches the hardware.",
        "Installez le paquet : sans ces fichiers, aucun changement n’atteint le matériel.",
        "请安装软件包：缺少这些文件时任何更改都无法写入硬件。",
        "Установите пакет: без этих файлов изменения не доходят до оборудования.",
    ),
    (
        "Revisa journalctl -u {unit}",
        "Check journalctl -u {unit}",
        "Consultez journalctl -u {unit}",
        "请查看 journalctl -u {unit}",
        "Смотрите journalctl -u {unit}",
    ),
    (
        "systemctl no respondió; el servicio puede estar en cualquier estado.",
        "systemctl did not answer; the service may be in any state.",
        "systemctl n’a pas répondu ; le service peut être dans n’importe quel état.",
        "systemctl 未响应；服务可能处于任意状态。",
        "systemctl не ответил; служба может быть в любом состоянии.",
    ),
    (
        "Otro componente escribe platform_profile y puede deshacer una escena.",
        "Another component writes platform_profile and can undo a scene.",
        "Un autre composant écrit platform_profile et peut annuler une scène.",
        "另一个组件会写入 platform_profile，可能撤销场景。",
        "Другой компонент пишет platform_profile и может отменить сцену.",
    ),
    (
        "Otra herramienta maneja el mismo controlador ITE. Ciérrala antes.",
        "Another tool drives the same ITE controller. Close it first.",
        "Un autre outil pilote le même contrôleur ITE. Fermez-le d’abord.",
        "另一个工具正在驱动同一 ITE 控制器。请先关闭它。",
        "Другая программа управляет тем же контроллером ITE. Закройте её.",
    ),
    (
        "Sin sensores no hay curva segura: el firmware conserva el control.",
        "Without sensors there is no safe curve: the firmware keeps control.",
        "Sans capteurs, pas de courbe sûre : le firmware garde le contrôle.",
        "没有传感器就没有安全曲线：固件保留控制权。",
        "Без датчиков нет безопасной кривой: управление остаётся у прошивки.",
    ),
    (
        "Temperatura crítica: deja que el firmware suba los ventiladores.",
        "Critical temperature: let the firmware raise the fans.",
        "Température critique : laissez le firmware accélérer les ventilateurs.",
        "温度危急：让固件提高风扇转速。",
        "Критическая температура: позвольте прошивке поднять обороты.",
    ),
    (
        "Carga sostenida alta. Un perfil más frío baja la temperatura.",
        "Sustained high load. A cooler profile brings the temperature down.",
        "Charge élevée soutenue. Un profil plus frais fait baisser la température.",
        "持续高负载。更凉的配置文件可降低温度。",
        "Длительная высокая нагрузка. Прохладный профиль снизит температуру.",
    ),
    ("Copiar JSON", "Copy JSON", "Copier le JSON", "复制 JSON", "Копировать JSON"),
    # Doctor: the opt-in release notice. It reads a version and nothing else.
    (
        "Avisos de versión",
        "Release notices",
        "Avis de version",
        "版本提醒",
        "Уведомления о версии",
    ),
    (
        "Desactivado por defecto · única conexión de red de la aplicación",
        "Off by default · the application's only network connection",
        "Désactivé par défaut · seule connexion réseau de l’application",
        "默认关闭 · 应用程序唯一的网络连接",
        "Выключено по умолчанию · единственное сетевое соединение приложения",
    ),
    (
        "Avisar de nuevas versiones",
        "Notify about new releases",
        "Signaler les nouvelles versions",
        "提醒新版本",
        "Сообщать о новых версиях",
    ),
    (
        "Consulta la página de publicaciones una vez al día. No descarga ni instala nada",
        "Asks the releases page once a day. It downloads and installs nothing",
        "Interroge la page des versions une fois par jour. Ne télécharge ni n’installe rien",
        "每天查询一次发布页面。不下载也不安装任何内容",
        "Запрашивает страницу релизов раз в сутки. Ничего не скачивает и не устанавливает",
    ),
    ("Estado", "State", "État", "状态", "Состояние"),
    (
        "Ver publicaciones",
        "View releases",
        "Voir les versions",
        "查看发布页",
        "Открыть релизы",
    ),
    ("consultando", "checking", "vérification", "查询中", "проверка"),
    ("al día", "up to date", "à jour", "已是最新", "актуальна"),
    (
        "no se pudo consultar",
        "could not be checked",
        "vérification impossible",
        "无法查询",
        "не удалось проверить",
    ),
    ("desactivado", "off", "désactivé", "已关闭", "выключено"),
    (
        "{version} disponible",
        "{version} available",
        "{version} disponible",
        "{version} 可用",
        "{version} доступна",
    ),
    (
        "{installed} · {latest} disponible",
        "{installed} · {latest} available",
        "{installed} · {latest} disponible",
        "{installed} · {latest} 可用",
        "{installed} · доступна {latest}",
    ),
    (
        "Solo la última publicación recibe soporte de seguridad.",
        "Only the latest release receives security support.",
        "Seule la dernière version reçoit un support de sécurité.",
        "仅最新发布版本获得安全支持。",
        "Поддержка безопасности предоставляется только последнему релизу.",
    ),
    (
        "No se cargó el aviso de versión: {error}",
        "The release notice could not be loaded: {error}",
        "L’avis de version n’a pas pu être chargé : {error}",
        "无法加载版本提醒：{error}",
        "Не удалось загрузить уведомление о версии: {error}",
    ),
    (
        "No se guardó el aviso de versión: {error}",
        "The release notice could not be saved: {error}",
        "L’avis de version n’a pas pu être enregistré : {error}",
        "无法保存版本提醒：{error}",
        "Не удалось сохранить уведомление о версии: {error}",
    ),
    (
        "control firmware",
        "firmware control",
        "contrôle du firmware",
        "固件控制",
        "управление прошивкой",
    ),
    (
        "controlador ITE detectado",
        "ITE controller detected",
        "Contrôleur ITE détecté",
        "已检测到 ITE 控制器",
        "Контроллер ITE обнаружен",
    ),
    ("no disponible", "unavailable", "indisponible", "不可用", "недоступно"),
    (
        "no publicado por el kernel",
        "not exposed by kernel",
        "non exposé par le noyau",
        "内核未提供",
        "не предоставляется ядром",
    ),
    (
        "{minimum}–{maximum} RPM · paso {step} RPM",
        "{minimum}–{maximum} RPM · step {step} RPM",
        "{minimum}–{maximum} RPM · pas de {step} RPM",
        "{minimum}–{maximum} RPM · 步长 {step} RPM",
        "{minimum}–{maximum} RPM · шаг {step} RPM",
    ),
    ("disponible", "available", "disponible", "可用", "доступно"),
    (
        "fan 1 {rpm} RPM",
        "fan 1 {rpm} RPM",
        "ventilateur 1 {rpm} RPM",
        "风扇 1 {rpm} RPM",
        "вентилятор 1 {rpm} об/мин",
    ),
    (
        "fan 2 {rpm} RPM",
        "fan 2 {rpm} RPM",
        "ventilateur 2 {rpm} RPM",
        "风扇 2 {rpm} RPM",
        "вентилятор 2 {rpm} об/мин",
    ),
    (
        "sin lecturas fiables",
        "no reliable readings",
        "aucune mesure fiable",
        "没有可靠读数",
        "нет надёжных показаний",
    ),
    ("Lecturas", "Readings", "Mesures", "读数", "Показания"),
    ("Servicio", "Service", "Service", "服务", "Служба"),
    ("Compartir", "Share", "Partager", "分享", "Поделиться"),
    ("Copiar informe", "Copy report", "Copier le rapport", "复制报告", "Копировать отчёт"),
    ("Guardar informe", "Save report", "Enregistrer le rapport", "保存报告", "Сохранить отчёт"),
    ("Listo", "Ready", "Prêt", "就绪", "Готово"),
    ("Revisar", "Review", "Vérifier", "检查", "Проверить"),
    ("Atención", "Attention", "Attention", "注意", "Внимание"),
    (
        "Informe Doctor copiado.",
        "Doctor report copied.",
        "Rapport de diagnostic copié.",
        "诊断报告已复制。",
        "Отчёт диагностики скопирован.",
    ),
    (
        "Guardar informe Doctor",
        "Save Doctor report",
        "Enregistrer le rapport de diagnostic",
        "保存诊断报告",
        "Сохранить отчёт диагностики",
    ),
    (
        "Informe Doctor guardado.",
        "Doctor report saved.",
        "Rapport de diagnostic enregistré.",
        "诊断报告已保存。",
        "Отчёт диагностики сохранён.",
    ),
    (
        "Idioma de la interfaz",
        "Interface language",
        "Langue de l’interface",
        "界面语言",
        "Язык интерфейса",
    ),
    (
        "El idioma elegido se aplicará al abrir Legion Control de nuevo.",
        "The selected language applies next time Legion Control opens.",
        "La langue choisie sera appliquée à la prochaine ouverture de Legion Control.",
        "所选语言将在下次打开 Legion Control 时应用。",
        "Выбранный язык будет применён при следующем запуске Legion Control.",
    ),
    (
        "Idioma guardado. Reinicia Legion Control para aplicarlo.",
        "Language saved. Restart Legion Control to apply it.",
        "Langue enregistrée. Redémarrez Legion Control pour l’appliquer.",
        "语言已保存。重启 Legion Control 后生效。",
        "Язык сохранён. Перезапустите Legion Control, чтобы применить его.",
    ),
    (
        "No se cargaron las escenas: {error}",
        "Could not load scenes: {error}",
        "Impossible de charger les scènes : {error}",
        "无法加载场景：{error}",
        "Не удалось загрузить сцены: {error}",
    ),
    (
        "No se puede leer el perfil actual.",
        "Could not read current profile.",
        "Impossible de lire le profil actuel.",
        "无法读取当前模式。",
        "Не удалось прочитать текущий профиль.",
    ),
    (
        "No se puede leer la ventilación actual.",
        "Could not read current fan settings.",
        "Impossible de lire les réglages actuels des ventilateurs.",
        "无法读取当前风扇设置。",
        "Не удалось прочитать текущие настройки вентиляторов.",
    ),
    (
        "La ventilación manual no está confirmada como Custom.",
        "Manual fan control is not confirmed as Custom.",
        "Le contrôle manuel des ventilateurs n’est pas confirmé comme Personnalisé.",
        "手动风扇控制未确认处于自定义模式。",
        "Ручное управление вентиляторами не подтверждено как пользовательское.",
    ),
    (
        "Custom sin ventilación manual no forma una escena completa.",
        "Custom without manual fans is not a complete scene.",
        "Personnalisé sans ventilateurs manuels ne forme pas une scène complète.",
        "没有手动风扇的自定义模式不是完整场景。",
        "Пользовательский режим без ручных вентиляторов не образует полную сцену.",
    ),
    (
        "No se guardó la escena: {error}",
        "Could not save scene: {error}",
        "Impossible d’enregistrer la scène : {error}",
        "无法保存场景：{error}",
        "Не удалось сохранить сцену: {error}",
    ),
    (
        "No se cargó la automatización: {error}",
        "Could not load automation: {error}",
        "Impossible de charger l’automatisation : {error}",
        "无法加载自动化：{error}",
        "Не удалось загрузить автоматизацию: {error}",
    ),
    (
        "No se guardó la automatización: {error}",
        "Could not save automation: {error}",
        "Impossible d’enregistrer l’automatisation : {error}",
        "无法保存自动化：{error}",
        "Не удалось сохранить автоматизацию: {error}",
    ),
    (
        "No se guardó el historial: {error}",
        "Could not save history: {error}",
        "Impossible d’enregistrer l’historique : {error}",
        "无法保存历史记录：{error}",
        "Не удалось сохранить историю: {error}",
    ),
    (
        "No se guardó el evento: {error}",
        "Could not save event: {error}",
        "Impossible d’enregistrer l’événement : {error}",
        "无法保存事件：{error}",
        "Не удалось сохранить событие: {error}",
    ),
    (
        "No se exportó el CSV: {error}",
        "Could not export CSV: {error}",
        "Impossible d’exporter le CSV : {error}",
        "无法导出 CSV：{error}",
        "Не удалось экспортировать CSV: {error}",
    ),
    (
        "No se pudo elegir el destino: {error}",
        "Could not choose destination: {error}",
        "Impossible de choisir la destination : {error}",
        "无法选择目标位置：{error}",
        "Не удалось выбрать место сохранения: {error}",
    ),
    (
        "No se pudo resolver la ruta de destino.",
        "Could not resolve destination path.",
        "Impossible de résoudre le chemin de destination.",
        "无法解析目标路径。",
        "Не удалось определить путь назначения.",
    ),
    (
        "No se guardó el informe: {error}",
        "Could not save report: {error}",
        "Impossible d’enregistrer le rapport : {error}",
        "无法保存报告：{error}",
        "Не удалось сохранить отчёт: {error}",
    ),
    (
        "Método no admitido: {method}",
        "Unsupported method: {method}",
        "Méthode non prise en charge : {method}",
        "不支持的方法：{method}",
        "Неподдерживаемый метод: {method}",
    ),
    (
        "Atajos locales de Legion Control.",
        "Local Legion Control shortcuts.",
        "Raccourcis locaux de Legion Control.",
        "Legion Control 本地快捷命令。",
        "Локальные команды Legion Control.",
    ),
    (
        "Muestra estado JSON solo lectura",
        "Show read-only JSON status",
        "Afficher l’état JSON en lecture seule",
        "显示只读 JSON 状态",
        "Показать статус JSON только для чтения",
    ),
    (
        "Genera informe Doctor solo lectura",
        "Generate read-only Doctor report",
        "Générer le rapport de diagnostic en lecture seule",
        "生成只读诊断报告",
        "Создать отчёт диагностики только для чтения",
    ),
    ("Emite JSON", "Output JSON", "Produire du JSON", "输出 JSON", "Вывести JSON"),
    (
        "Detiene curva manual y devuelve ventiladores al firmware",
        "Stop manual curve and return fans to firmware",
        "Arrêter la courbe manuelle et rendre les ventilateurs au firmware",
        "停止手动曲线并将风扇交还给固件",
        "Остановить ручную кривую и вернуть вентиляторы прошивке",
    ),
    (
        "Aplica una escena guardada",
        "Apply a saved scene",
        "Appliquer une scène enregistrée",
        "应用已保存的场景",
        "Применить сохранённую сцену",
    ),
    (
        "Orden no admitida.",
        "Unsupported command.",
        "Commande non prise en charge.",
        "不支持的命令。",
        "Неподдерживаемая команда.",
    ),
    (
        "Conservación de batería",
        "Battery conservation",
        "Conservation de la batterie",
        "电池保护",
        "Сохранение батареи",
    ),
    (
        "Reduce el desgaste cuando el portátil permanece conectado",
        "Reduces wear while the laptop stays plugged in",
        "Réduit l’usure lorsque le portable reste branché",
        "笔记本持续接通电源时减少损耗",
        "Снижает износ, когда ноутбук остаётся подключённым",
    ),
    ("Bloqueo Fn", "Fn lock", "Verrouillage Fn", "Fn 锁定", "Блокировка Fn"),
    (
        "Cambia el comportamiento principal de la fila de funciones",
        "Changes the primary behaviour of the function-key row",
        "Modifie le comportement principal de la rangée de touches de fonction",
        "更改功能键行的主要行为",
        "Меняет основное поведение ряда функциональных клавиш",
    ),
    (
        "Alimentación de cámara",
        "Camera power",
        "Alimentation de la caméra",
        "摄像头电源",
        "Питание камеры",
    ),
    (
        "Conecta o corta la cámara integrada",
        "Connects or disconnects the built-in camera",
        "Connecte ou coupe la caméra intégrée",
        "连接或断开内置摄像头",
        "Включает или отключает встроенную камеру",
    ),
    ("7 días", "7 days", "7 jours", "7 天", "7 дней"),
    (
        "Temperatura crítica: {temperature} °C. Reduce carga y restaura firmware si dudas.",
        "Critical temperature: {temperature} °C. Reduce load and restore firmware if unsure.",
        "Température critique : {temperature} °C. Réduisez la charge et restaurez le firmware en cas de doute.",
        "温度严重：{temperature} °C。如不确定，请降低负载并恢复固件控制。",
        "Критическая температура: {temperature} °C. Снизьте нагрузку и восстановите прошивку, если сомневаетесь.",
    ),
    (
        "Temperatura elevada: {temperature} °C.",
        "High temperature: {temperature} °C.",
        "Température élevée : {temperature} °C.",
        "温度过高：{temperature} °C。",
        "Высокая температура: {temperature} °C.",
    ),
    ("cargando", "charging", "en charge", "充电中", "заряжается"),
    ("en uso", "in use", "en cours d’utilisation", "使用中", "используется"),
    ("completa", "full", "chargée", "已充满", "полная"),
    ("sin cargar", "not charging", "sans charge", "未充电", "не заряжается"),
    ("estado desconocido", "unknown state", "état inconnu", "未知状态", "неизвестное состояние"),
    ("Hielo", "Ice", "Glace", "冰霜", "Лёд"),
    ("Bosque", "Forest", "Forêt", "森林", "Лес"),
    ("Neón", "Neon", "Néon", "霓虹", "Неон"),
    ("Brasa", "Ember", "Braise", "余烬", "Угли"),
    ("Nocturno", "Night", "Nuit", "夜间", "Ночь"),
    ("Ajedrez", "Checker", "Damier", "棋盘", "Шахматы"),
    ("Versión", "Version", "Version", "版本", "Версия"),
    ("Aplicar ahora", "Apply now", "Appliquer maintenant", "立即应用", "Применить сейчас"),
    ("Reiniciar ahora", "Restart now", "Redémarrer maintenant", "立即重启", "Перезапустить сейчас"),
    (
        "Reinicia Legion Control · se pierden los cambios sin aplicar",
        "Restarts Legion Control · unapplied changes are lost",
        "Redémarre Legion Control · les modifications non appliquées sont perdues",
        "重启 Legion Control · 未应用的更改将丢失",
        "Перезапускает Legion Control · несохранённые изменения теряются",
    ),
    (
        "Se aplica solo, poco después de cada cambio",
        "Applied automatically, shortly after each change",
        "Appliqué automatiquement, peu après chaque modification",
        "每次更改后稍候自动生效",
        "Применяется автоматически, вскоре после каждого изменения",
    ),
    (
        "Restablecer curva",
        "Reset curve",
        "Réinitialiser la courbe",
        "重置曲线",
        "Сбросить кривую",
    ),
    (
        "Personalizado · lo activa la curva o la RPM fija",
        "Custom · set by the curve or fixed RPM",
        "Personnalisé · activé par la courbe ou les RPM fixes",
        "自定义 · 由曲线或固定转速激活",
        "Пользовательский · включается кривой или фиксированными об/мин",
    ),
)

_CATALOGS: Final = {
    "en": _catalog(_ENTRIES, 0),
    "fr": _catalog(_ENTRIES, 1),
    "zh": _catalog(_ENTRIES, 2),
    "ru": _catalog(_ENTRIES, 3),
}


def normalize_language(value: str | None) -> str | None:
    """Return a supported base language code, or ``None``."""
    if not value:
        return None
    code = value.replace("-", "_").split("_", maxsplit=1)[0].lower()
    return code if code in LANGUAGES else None


def system_language() -> str:
    for variable in ("LEGION_CONTROL_LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        language = normalize_language(os.environ.get(variable))
        if language is not None:
            return language
    configured, _encoding = locale.getlocale()
    return normalize_language(configured) or DEFAULT_LANGUAGE


def set_language(language: str | None) -> str:
    """Set active language, returning normalized selection."""
    global _ACTIVE_LANGUAGE
    _ACTIVE_LANGUAGE = normalize_language(language) or DEFAULT_LANGUAGE
    return _ACTIVE_LANGUAGE


def active_language() -> str:
    return _ACTIVE_LANGUAGE


def translate(message: str, /, **values: object) -> str:
    """Translate a Spanish source message, preserving a safe source fallback."""
    localized = _CATALOGS.get(_ACTIVE_LANGUAGE, {}).get(message, message)
    return localized.format(**values) if values else localized


def localize_widget_tree(root: object) -> None:
    """Translate static GTK text after a page finishes building.

    GTK widgets expose their user-facing text through GObject properties.  A
    single pass keeps page constructors readable and also covers accessibility
    tooltips.  Dynamic messages still use :func:`translate` at their update
    site.

    The walk carries no seen-set.  A GTK widget tree is acyclic, so one buys
    nothing, and de-duplicating by ``id()`` was unsound: PyGObject builds a
    fresh wrapper per ``get_first_child`` call, and a freed wrapper's address is
    handed straight to the next one, so an unrelated widget can inherit an
    address already recorded as seen and be skipped without translating.
    """
    pending = [root]
    properties = ("title", "subtitle", "description", "tooltip-text", "label")
    while pending:
        widget = pending.pop()
        find_property = getattr(widget, "find_property", None)
        get_property = getattr(widget, "get_property", None)
        set_property = getattr(widget, "set_property", None)
        if callable(find_property) and callable(get_property) and callable(set_property):
            for name in properties:
                if find_property(name) is None:
                    continue
                value = get_property(name)
                if isinstance(value, str) and value:
                    localized = translate(value)
                    if localized != value:
                        set_property(name, localized)
        child = getattr(widget, "get_first_child", lambda: None)()
        while child is not None:
            pending.append(child)
            child = getattr(child, "get_next_sibling", lambda: None)()


class LanguageStore:
    """Persist an optional explicit language without changing the system locale."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_language_path()

    def load(self) -> str | None:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return normalize_language(document.get("language")) if isinstance(document, dict) else None

    def save(self, language: str) -> None:
        normalized = normalize_language(language)
        if normalized is None:
            raise ValueError(f"Unsupported language: {language}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"version": 1, "language": normalized}) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


def default_language_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "legion-control" / "language.json"


def configure_startup_language() -> str:
    """Use environment override, then saved preference, then system locale."""
    override = normalize_language(os.environ.get("LEGION_CONTROL_LANGUAGE"))
    preference = LanguageStore().load()
    return set_language(override or preference or system_language())
