"""Context-sensitive proposals. Application metadata only lives in memory."""
from dataclasses import dataclass


@dataclass
class Proposal:
    reason: str
    start: float = 0
    end: float = 0


class AttentionPolicy:
    def __init__(self):
        self.last_prompt = float('-inf')
        self.snoozed_until = 0
        self.baseline = ''
        self.candidate = ''
        self.candidate_since = 0
        self.idle_start = None
        self.was_enabled = False
        self.previous_at = None
        self.enabled_at = None
        self.prompt_times = []
        self.last_answer = 0

    def acknowledge(self, now, snooze=0):
        self.last_prompt = now
        self.last_answer = now
        self.snoozed_until = now + snooze
        if self.candidate:
            self.baseline = self.candidate
        self.candidate = ''
        self.idle_start = None

    def shown(self, now):
        self.last_prompt = now
        self.prompt_times.append(now)

    def reset(self):
        self.was_enabled = False
        self.enabled_at = None
        self.baseline = self.candidate = ''
        self.idle_start = None

    def observe(self, sample, config, current, dialog_open=False):
        if not config.get('monitor_enabled', False):
            self.reset()
            self.previous_at = sample.at
            return None
        if not self.was_enabled:
            self.was_enabled = True
            self.enabled_at = sample.at
        if self.previous_at is not None and sample.at - self.previous_at > 90 and current and current['kind'] == 'active':
            self.idle_start = max(self.previous_at, current['start'])
        self.previous_at = sample.at
        threshold = config.get('idle_minutes', 3) * 60
        if sample.idle is not None and sample.idle >= threshold:
            if current and current['kind'] == 'active' and self.idle_start is None:
                self.idle_start = max(sample.at - sample.idle, current['start'])
            return None
        if dialog_open or sample.fullscreen or sample.own or sample.at < self.snoozed_until:
            return None
        self.prompt_times = [t for t in self.prompt_times if sample.at - t < 3600]
        if len(self.prompt_times) >= config.get('max_prompts_hour', 6):
            return None
        if sample.at - self.last_prompt < config.get('cooldown_minutes', 5) * 60:
            return None
        if sample.idle is None:
            return None
        if self.idle_start is not None and sample.idle < 30:
            start = self.idle_start
            self.idle_start = None
            if current and current['kind'] == 'active' and start >= current['start'] and sample.at - start >= threshold:
                return Proposal('idle_return', start, sample.at - sample.idle)
        safe_moment = 2 <= sample.idle <= 30
        if safe_moment and not current and sample.at - self.enabled_at >= 30:
            return Proposal('untracked')
        if safe_moment and current and current['kind'] == 'idle' and sample.at - current['start'] >= 60:
            return Proposal('resume')
        if config.get('observation_mode', 'idle') == 'app' and sample.context:
            if not self.baseline:
                self.baseline = sample.context
            elif sample.context == self.baseline:
                self.candidate = ''
            elif sample.context != self.candidate:
                self.candidate, self.candidate_since = sample.context, sample.at
            elif safe_moment and sample.at - self.candidate_since >= config.get('change_seconds', 30):
                return Proposal('context_change')
        checkin = config.get('checkin_minutes', 20)
        if checkin and safe_moment and current and current['kind'] == 'active':
            last = max(current['start'], self.last_answer, self.enabled_at)
            if sample.at - last >= checkin * 60:
                return Proposal('long_activity')
        return None
