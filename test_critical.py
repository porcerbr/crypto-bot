"""
test_critical.py - Testes dos fixes críticos.

Executa com: python -m pytest test_critical.py -v
"""

import pytest
import math
from utils import jpy_to_usd, calc_pnl_usd
from ai_validator import _get_technical_fallback_score


class TestJPYConversion:
    """Testes de conversão de pares JPY."""
    
    def test_jpy_conversion_sanity(self):
        """Teste: USDJPY fora do range usa fallback."""
        # Cotação inválida
        result_invalid = jpy_to_usd(1000, 0)
        result_fallback = jpy_to_usd(1000, 150.0)
        assert result_invalid == result_fallback
        
        # Cotação muito alta
        result_high = jpy_to_usd(1000, 500)
        assert result_high == result_fallback
        
        # Cotação muito baixa
        result_low = jpy_to_usd(1000, 50)
        assert result_low == result_fallback
    
    def test_jpy_conversion_valid(self):
        """Teste: USDJPY válida faz cálculo correto."""
        result = jpy_to_usd(1500, 150)
        assert result == 10.0
        
        result = jpy_to_usd(3000, 150)
        assert result == 20.0


class TestPnLUSDValidation:
    """Testes de cálculo de P&L com validação."""
    
    def test_pnl_usd_invalid_inputs(self):
        """Teste: P&L com inputs inválidos retorna 0."""
        assert calc_pnl_usd("EURUSD", "BUY", 0, 1.1, 0.1) == 0.0
        assert calc_pnl_usd("EURUSD", "BUY", 1.0, -1, 0.1) == 0.0
        assert calc_pnl_usd("EURUSD", "BUY", 1.0, 1.1, -0.1) == 0.0
        assert calc_pnl_usd("EURUSD", "BUY", 1.0, 1.1, 0) == 0.0
    
    def test_pnl_usd_none_inputs(self):
        """Teste: P&L com None retorna 0."""
        assert calc_pnl_usd("EURUSD", "BUY", None, 1.1, 0.1) == 0.0
        assert calc_pnl_usd("EURUSD", "BUY", 1.0, None, 0.1) == 0.0
        assert calc_pnl_usd("EURUSD", "BUY", 1.0, 1.1, None) == 0.0
    
    def test_pnl_usd_nan_inputs(self):
        """Teste: P&L com NaN retorna 0."""
        assert calc_pnl_usd("EURUSD", "BUY", float('nan'), 1.1, 0.1) == 0.0
        assert calc_pnl_usd("EURUSD", "BUY", 1.0, float('inf'), 0.1) == 0.0
    
    def test_pnl_usd_buy_valid(self):
        """Teste: P&L BUY válido."""
        # EURUSD: entry=1.1, exit=1.1, lot=0.01
        # P&L = (1.1-1.1) * 100000 * 0.01 = 0
        result = calc_pnl_usd("EURUSD", "BUY", 1.1, 1.1, 0.01)
        assert result == 0.0
        
        # entry=1.1, exit=1.2, lot=0.01
        # P&L = (1.2-1.1) * 100000 * 0.01 = 100
        result = calc_pnl_usd("EURUSD", "BUY", 1.1, 1.2, 0.01)
        assert result == 100.0
    
    def test_pnl_usd_sell_valid(self):
        """Teste: P&L SELL válido."""
        # entry=1.1, exit=1.0, lot=0.01
        # P&L = (1.1-1.0) * 100000 * 0.01 = 100
        result = calc_pnl_usd("EURUSD", "SELL", 1.1, 1.0, 0.01)
        assert result == 100.0
    
    def test_pnl_usd_jpy_conversion(self):
        """Teste: P&L JPY converte para USD."""
        # USDJPY: entry=150, exit=151, lot=0.01
        # P&L = (151-150) * 100 * 0.01 = 10 (em JPY)
        # Em USD = 10 / 150 = 0.07
        result = calc_pnl_usd("USDJPY", "BUY", 150, 151, 0.01, usdjpy_price=150)
        assert abs(result - 0.07) < 0.01


class TestTechnicalFallback:
    """Testes do fallback técnico sem IA."""
    
    def test_technical_fallback_score_buy(self):
        """Teste: Fallback técnico gera score para BUY."""
        h1 = {
            "price": 1.1,
            "ema200": 1.05,
            "ema9": 1.08,
            "ema21": 1.06,
            "macd_bull": True,
            "adx": 28,
            "candle_bull": True,
        }
        
        score, reason = _get_technical_fallback_score(h1, "BUY")
        assert score >= 5
        assert isinstance(reason, str)
        assert len(reason) > 0
    
    def test_technical_fallback_score_sell(self):
        """Teste: Fallback técnico gera score para SELL."""
        h1 = {
            "price": 1.0,
            "ema200": 1.05,
            "ema9": 1.01,
            "ema21": 1.06,
            "macd_bear": True,
            "adx": 28,
            "candle_bear": True,
        }
        
        score, reason = _get_technical_fallback_score(h1, "SELL")
        assert score >= 5
        assert isinstance(reason, str)
    
    def test_technical_fallback_weak_setup(self):
        """Teste: Setup fraco gera score baixo."""
        h1 = {
            "price": 1.0,
            "ema200": 1.0,
            "ema9": 1.0,
            "ema21": 1.0,
            "macd_bull": False,
            "adx": 10,
            "candle_bull": False,
        }
        
        score, reason = _get_technical_fallback_score(h1, "BUY")
        assert score < 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
