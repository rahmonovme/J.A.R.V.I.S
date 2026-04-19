# core/gemini_client.py
# Shared Gemini client factory — uses the NEW google.genai package.
# All project files should use this instead of the deprecated google.generativeai.
#
# Smart Model Rotation — maximizes free-tier throughput by cascading
# through every available model bucket before giving up.

import json
import sys
import time
from pathlib import Path
from datetime import date
from typing import List

from core.logger import logger


# ═══════════════════════════════════════════════════════════════════
# MODEL POOLS — Exactly matched to provided Dashboard Limits
# ═══════════════════════════════════════════════════════════════════
#
#  Model                           │ RPM │ TPM   │ RPD  │ Notes
#  ────────────────────────────────┼─────┼───────┼──────┼─────────────────
#  gemini-3.1-flash-lite-preview   │ 15  │ 250K  │ 500  │ ★ Primary (High RPD)
#  gemini-3-flash-preview          │  5  │ 250K  │  20  │ Stable
#  gemini-2.5-flash-lite           │ 10  │ 250K  │  20  │ Fast
#  gemini-2.5-flash                │  5  │ 250K  │  20  │ Quality
#
# ═══════════════════════════════════════════════════════════════════

# Text generation fallback chain (ordered: capacity → speed)
_TEXT_CHAIN = [
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
]

# Vision/image fallback chain (ordered: quality → capacity)
_VISION_CHAIN = [
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
]

# Legacy alias — kept for backward compatibility
_FALLBACK_CHAIN = _TEXT_CHAIN

# 503 retry configuration
_MAX_503_RETRIES = 3
_503_DELAYS = [1.5, 3.0, 5.0]


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
API_LIMITS_PATH = BASE_DIR / "config" / "api_limits.json"
MODEL_CONFIG_PATH = BASE_DIR / "config" / "model_config.json"

# In-memory cooldown for 429 errors (15 minute block)
_MODEL_COOLDOWN = {}
_COOLDOWN_SECONDS = 900

class ModelRegistry:
    """Handles dynamic model scanning, identification, and role-based routing."""
    
    @staticmethod
    def get_config() -> dict:
        defaults = {"roles": {}, "chains": {}, "custom_limits": {}, "inventory": []}
        if not MODEL_CONFIG_PATH.exists():
            return defaults
        try:
            with open(MODEL_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Ensure all keys exist
                for k, v in defaults.items():
                    if k not in data: data[k] = v
                return data
        except Exception as e:
            print(f"[DEBUG] ModelRegistry: Error reading config: {e}")
            return defaults

    @staticmethod
    def save_config(config: dict):
        with open(MODEL_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)

    @staticmethod
    def scan_models():
        """Fetches all models from Google API and syncs inventory metadata."""
        from google import genai
        try:
            client = genai.Client(api_key=get_api_key())
            inventory = []
            for m in client.models.list():
                actions = m.supported_actions or []
                # Lite models NEVER support Bidi/Realtime API
                is_bidi = any("BIDI" in a.upper() for a in actions) and "-lite" not in m.name.lower()
                
                inventory.append({
                    "name": m.name,
                    "display_name": m.display_name,
                    "description": m.description,
                    "input_limit": m.input_token_limit,
                    "output_limit": m.output_token_limit,
                    "actions": actions,
                    "is_bidi": is_bidi
                })
            
            config = ModelRegistry.get_config()
            config["inventory"] = inventory
            ModelRegistry.save_config(config)
            
            return inventory
        except Exception as e:
            logger.log("REGISTRY", f"Scan failed: {e}", level="ERR")
            return []

    @staticmethod
    def auto_align_roles():
        """
        Smart-analyzes available models and automatically maps them to project roles.
        Categories: voice, planner, vision, text.
        """
        logger.log("REGISTRY", "Starting smart model alignment...", level="SYS")
        inventory = ModelRegistry.scan_models()
        if not inventory:
            return False
            
        config = ModelRegistry.get_config()
        custom_limits = config.get("custom_limits", {})
        
        roles = {}
        chains = {}
        
        voice_pool = []
        planner_pool = []
        vision_pool = []
        text_pool = []
        
        for m in inventory:
            mname = m["name"].replace("models/", "")
            low_name = mname.lower()
            limit = m.get("input_limit", 0)
            is_bidi = m.get("is_bidi", False)
            
            # Base Score: Input Limit
            base_score = limit
            
            # Bonus for custom limits (user-preferred)
            if mname in custom_limits or f"models/{mname}" in custom_limits:
                base_score *= 5
            
            # Voice Heuristic (Must be Bidi)
            if is_bidi:
                # Live preview models are top tier for voice
                if "live-preview" in low_name:
                    voice_pool.append((base_score * 10, mname))
                else:
                    voice_pool.append((base_score, mname))
            
            # Planner Heuristic (Pro models or high limits)
            if "pro" in low_name:
                planner_pool.append((base_score * 10, mname)) 
            elif "flash-lite" in low_name:
                planner_pool.append((base_score * 5, mname)) # Lite is good for planning too
            else:
                planner_pool.append((base_score, mname))
                
            # Vision Heuristic (Flash or Pro)
            if "flash" in low_name or "pro" in low_name:
                vision_pool.append((base_score, mname))
                
            # Text Heuristic (Prefer Lite > Flash > Pro for cost/speed)
            if "flash-lite" in low_name:
                text_pool.append((base_score * 10, mname))
            elif "flash" in low_name:
                text_pool.append((base_score * 5, mname))
            else:
                text_pool.append((base_score, mname))

        # Helper to sort and extract names
        def pick_chain(pool, count=5):
            pool.sort(key=lambda x: x[0], reverse=True)
            return [x[1] for x in pool[:count]]

        # Assignment Logic
        if voice_pool:
            v_chain = pick_chain(voice_pool)
            roles["voice"] = v_chain[0]
            chains[v_chain[0]] = v_chain[1:]
            
        if planner_pool:
            p_chain = pick_chain(planner_pool)
            roles["planner"] = p_chain[0]
            chains[p_chain[0]] = p_chain[1:]
            
        if vision_pool:
            vis_chain = pick_chain(vision_pool)
            roles["vision"] = vis_chain[0]
            chains[vis_chain[0]] = vis_chain[1:]
            
        if text_pool:
            t_chain = pick_chain(text_pool)
            roles["text"] = t_chain[0]
            chains[t_chain[0]] = t_chain[1:]

        config["roles"]  = roles
        config["chains"] = chains
        ModelRegistry.save_config(config)
        logger.log("REGISTRY", f"Smart setup complete: {len(roles)} roles aligned.", level="SYS")
        return True

    @staticmethod
    def get_chain(role: str) -> List[str]:
        """Returns the fallback model chain for a specific role (planner, vision, etc)."""
        config = ModelRegistry.get_config()
        return config.get("chains", {}).get(role, [])

    @staticmethod
    def get_voice_chain(default_model: str = "models/gemini-2.0-flash-exp") -> list:
        """Returns a prioritized list of models for Live Voice/Vision (MUST support Bidi)."""
        config = ModelRegistry.get_config()
        base = config["roles"].get("voice") or default_model
        return ModelRegistry._resolve_chain(base, requires_bidi=True)

    @staticmethod
    def get_vision_chain(default_model: str = "models/gemini-2.0-flash-exp") -> list:
        """Returns a prioritized list of models for Vision (prioritizes Bidi for Realtime)."""
        config = ModelRegistry.get_config()
        base = config["roles"].get("vision") or default_model
        # For our Live context in screen_processor, we strongly prefer Bidi models
        return ModelRegistry._resolve_chain(base, requires_bidi=True)

    @staticmethod
    def _resolve_chain(base_model: str, requires_bidi=False) -> list:
        """
        Builds a fallback chain for a specific role, filtering out exhausted models.
        """
        config = ModelRegistry.get_config()
        inventory = config.get("inventory", [])
        exhausted_set = set(_get_exhausted_models().keys())
        
        def is_exhausted(mname):
            # Check both 'models/name' and 'name'
            raw = mname.replace("models/", "")
            return raw in exhausted_set or f"models/{raw}" in exhausted_set

        def is_bidi(mname):
            match = next((m for m in inventory if m["name"] == mname or m["name"] == f"models/{mname}"), None)
            if match:
                return match.get("is_bidi", False)
            # Hardcoded fallback logic: flash is bidi, lite is NOT
            m_lower = mname.lower()
            return "-flash" in m_lower and "-lite" not in m_lower

        # 1. Start with the base model if not exhausted
        chain = []
        if not is_exhausted(base_model):
            if not requires_bidi or is_bidi(base_model):
                chain.append(base_model)
        
        # 2. Add fallback chain if configured
        fallback_names = config["chains"].get(base_model, [])
        for f in fallback_names:
            if not is_exhausted(f) and f not in chain:
                if not requires_bidi or is_bidi(f):
                    chain.append(f)
                    
        # 3. Last resort: Any non-exhausted model in inventory that fits the requirement
        if not chain:
            for m in inventory:
                mname = m["name"]
                if not is_exhausted(mname) and mname not in chain:
                    if not requires_bidi or m.get("is_bidi"):
                        chain.append(mname)
        
        return chain if chain else [base_model]

    @staticmethod
    def get_primary(role: str, default: str) -> str:
        """Returns the primary model for a specific role."""
        config = ModelRegistry.get_config()
        return config.get("roles", {}).get(role, default)

def get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _safe_load_json(path: Path) -> dict:
    """Retries loading JSON to handle concurrent access gracefully."""
    for _ in range(5):
        try:
            if not path.exists(): return {}
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            time.sleep(0.1)
    return {}

def _get_exhausted_models() -> dict:
    return _safe_load_json(API_LIMITS_PATH)

def _safe_save_json(path: Path, data: dict):
    """Retries saving JSON to handle concurrent access gracefully."""
    for _ in range(5):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            return
        except IOError:
            time.sleep(0.1)

def _resolve_chain(requested_model: str, chain: List[str]) -> List[str]:
    """
    Builds the model list to try:
    1. If the requested model is in the chain, start from that position onward.
    2. If not, prepend it before the full chain.
    3. Filter out models already exhausted today.
    """
    if requested_model in chain:
        models_to_try = chain[chain.index(requested_model):]
    else:
        # Custom model not in our chain — try it first, then fall through
        models_to_try = [requested_model] + chain

    # 1. Remove today's hard-exhausted models (RPD reached)
    try:
        limits = _safe_load_json(API_LIMITS_PATH)
        today_str = date.today().isoformat()
        
        # Purge stale keys
        stale_keys = [m for m, d in limits.items() if d != today_str]
        for k in stale_keys:
            del limits[k]

        models_to_try = [m for m in models_to_try if m not in limits]
    except Exception:
        pass

    # 2. Apply dynamic cooldown (429/TPM/RPM temporary blocks)
    now = time.time()
    active_cooldowns = {m: exp for m, exp in _MODEL_COOLDOWN.items() if exp > now}
    
    # Update global state for next call
    _MODEL_COOLDOWN.clear()
    _MODEL_COOLDOWN.update(active_cooldowns)
    
    filtered = [m for m in models_to_try if m not in active_cooldowns]
    
    if not filtered:
        # If ALL models are on cooldown, return the least-blocked one or full list
        return models_to_try
        
    return filtered


# Backward-compatible alias
def _get_available_models(requested_model: str) -> List[str]:
    # Try to resolve via planner chain if not specified
    chain = ModelRegistry.get_chain("planner") or _TEXT_CHAIN
    return _resolve_chain(requested_model, chain)


def _mark_model_exhausted(model: str):
    """Applies a 15-minute cooldown to the model."""
    _MODEL_COOLDOWN[model] = time.time() + _COOLDOWN_SECONDS
    logger.log("SYS", f"Coordinated cooldown applied to {model} (15m).", level="WARN")


def _try_with_retries(client, model: str, contents, config=None) -> str:
    """
    Attempts a single model with 503-aware retries.
    Returns response text on success, raises on permanent failure.
    """
    last_err = None
    for attempt in range(_MAX_503_RETRIES):
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            return response.text.strip()
        except Exception as e:
            last_err = e
            err_msg = str(e).lower()

            if "503" in err_msg or "unavailable" in err_msg:
                delay = _503_DELAYS[min(attempt, len(_503_DELAYS) - 1)]
                if attempt < _MAX_503_RETRIES - 1:
                    print(f"[GeminiClient] ⚠️ 503 on {model} (attempt {attempt+1}/{_MAX_503_RETRIES}) — retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                # Last retry failed — let caller handle fallback
                raise

            # Non-503 error — don't retry, propagate immediately
            raise

    raise last_err


def ask(prompt: str, model: str = None,
        system_instruction: str = None) -> str:
    """Simple one-shot text generation with smart model rotation."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=get_api_key())

    config = None
    if system_instruction:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction
        )

    # Dynamic lookup: Use planner role as default for text generation
    primary = ModelRegistry.get_primary("planner", "models/gemini-3.1-flash-lite-preview")
    
    # If no model provided, start with the primary role model.
    # If model provided, use it as the start of the chain.
    target_model = model or primary
    
    # Get the chain for this role
    chain = ModelRegistry.get_chain("planner") or _TEXT_CHAIN
    models_to_try = _resolve_chain(target_model, chain)

    last_err = None
    for idx, m in enumerate(models_to_try):
        try:
            return _try_with_retries(client, m, prompt, config)
        except Exception as e:
            last_err = e
            err_msg = str(e).lower()

            if "429" in err_msg or "quota" in err_msg or "exhausted" in err_msg:
                _mark_model_exhausted(m)
                if idx < len(models_to_try) - 1:
                    print(f"[GeminiClient] 🔄 {m} exhausted → switching to {models_to_try[idx+1]}...")
                continue

            if "503" in err_msg or "unavailable" in err_msg:
                # All 503 retries for this model failed — try next model
                if idx < len(models_to_try) - 1:
                    print(f"[GeminiClient] 🔄 {m} unavailable → switching to {models_to_try[idx+1]}...")
                continue

            # Other error — stop immediately
            raise e

    raise last_err


def ask_with_image(prompt: str, image_data: bytes,
                   mime_type: str = "image/png",
                   model: str = None) -> str:
    """One-shot vision generation with smart model rotation (uses VISION chain)."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=get_api_key())

    # Dynamic lookup for vision tasks
    primary = ModelRegistry.get_primary("vision", "models/gemini-3.1-flash-lite-preview")
    
    target_model = model or primary
    chain = ModelRegistry.get_chain("vision") or _VISION_CHAIN
    models_to_try = _resolve_chain(target_model, chain)

    last_err = None
    for idx, m in enumerate(models_to_try):
        try:
            return _try_with_retries(client, m, contents)
        except Exception as e:
            last_err = e
            err_msg = str(e).lower()

            if "429" in err_msg or "quota" in err_msg or "exhausted" in err_msg:
                _mark_model_exhausted(m)
                if idx < len(models_to_try) - 1:
                    print(f"[GeminiClient] 🔄 {m} exhausted → switching to {models_to_try[idx+1]}...")
                continue

            if "503" in err_msg or "unavailable" in err_msg:
                if idx < len(models_to_try) - 1:
                    print(f"[GeminiClient] 🔄 {m} unavailable → switching to {models_to_try[idx+1]}...")
                continue

            raise e

    raise last_err
