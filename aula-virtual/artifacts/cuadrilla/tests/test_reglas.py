"""Rules engine against the documented examples (PRD §7, spec §8.4, EXP y Coins §2-5). No database."""

import unittest
from datetime import date, datetime, timedelta, timezone

from rules import levels, mastery, redemption, risk, scoring, spacing
from rules.calendar import semana_de
from rules.params import DEFAULT_PARAMS as P, Params
from rules.selection import elegir_retos_clase, sortear_tema


class ExpTest(unittest.TestCase):
    def test_valores_por_nivel_y_mitad_con_pistas_o_parcial(self):
        self.assertEqual([scoring.exp_reto(n, "correcto", 0, False, P) for n in levels.NIVELES], [50, 100, 150, 200])
        self.assertEqual(scoring.exp_reto("intermedio", "correcto", 1, False, P), 50)
        self.assertEqual(scoring.exp_reto("intermedio", "parcial", 0, False, P), 50)
        # Partial AND hints is still half, never a quarter.
        self.assertEqual(scoring.exp_reto("intermedio", "parcial", 2, False, P), 50)
        self.assertEqual(scoring.exp_reto("avanzado", "incorrecto", 0, False, P), 0)

    def test_repaso_multiplica_despues_de_la_regla_de_pistas(self):
        self.assertEqual(scoring.exp_reto("intermedio", "correcto", 1, True, P), 75)   # 50 × 1,5
        self.assertEqual(scoring.exp_reto("avanzado", "correcto", 0, True, P), 225)

    def test_quiz_perfecto_por_nivel(self):
        """3 class challenges + 1 review + completed + perfect: 475 / 700 / 925 / 1 150."""
        esperado = {"basico": 475, "intermedio": 700, "avanzado": 925, "maestria": 1150}
        for nivel, total in esperado.items():
            retos = 3 * scoring.exp_reto(nivel, "correcto", 0, False, P) + scoring.exp_reto(nivel, "correcto", 0, True, P)
            bonos = scoring.bonos_quiz([("correcto", 0)] * 4, 4, P)
            self.assertEqual(retos + bonos["completado"] + bonos["perfecto"], total, nivel)

    def test_bono_completado_aunque_falle_y_perfecto_solo_sin_pistas(self):
        self.assertEqual(scoring.bonos_quiz([("incorrecto", 0)] * 4, 4, P), {"completado": 100, "perfecto": 0})
        self.assertEqual(scoring.bonos_quiz([("correcto", 0)] * 3 + [("correcto", 1)], 4, P)["perfecto"], 0)
        self.assertEqual(scoring.bonos_quiz([("correcto", 0)] * 3, 4, P), {"completado": 0, "perfecto": 0})

    def test_reto_semanal(self):
        self.assertEqual(scoring.exp_semanal("correcto", 0, P), 500)
        self.assertEqual(scoring.exp_semanal("correcto", 2, P), 250)
        self.assertEqual(scoring.exp_semanal("incorrecto", 0, P), 100)


class CoinsTest(unittest.TestCase):
    def test_puntaje_del_quiz_solo_con_verificables(self):
        self.assertEqual(scoring.puntaje_quiz([("correcto", 0), ("correcto", 1), ("parcial", 0), ("incorrecto", 0)]), 50)
        self.assertIsNone(scoring.puntaje_quiz([]))

    def test_coins_del_quiz_por_nivel_desde_75(self):
        self.assertEqual(scoring.coins_quiz(75, "basico", P), 5)
        self.assertEqual(scoring.coins_quiz(100, "avanzado", P), 5)
        self.assertEqual(scoring.coins_quiz(80, "maestria", P), 10)
        self.assertEqual(scoring.coins_quiz(74.9, "maestria", P), 0)
        self.assertEqual(scoring.coins_quiz(None, "basico", P), 0)

    def test_coins_del_semanal_y_del_podio(self):
        self.assertEqual(scoring.coins_semanal("intermedio", "correcto", 0, P), 5)
        self.assertEqual(scoring.coins_semanal("avanzado", "correcto", 0, P), 10)
        self.assertEqual(scoring.coins_semanal("maestria", "correcto", 0, P), 10)
        self.assertEqual(scoring.coins_semanal("avanzado", "correcto", 1, P), 0)
        self.assertEqual(scoring.coins_semanal("avanzado", "incorrecto", 0, P), 0)
        self.assertEqual([scoring.coins_podio(i, P) for i in (1, 2, 3, 4)], [120, 90, 60, 0])

    def test_canje_del_30_al_50(self):
        self.assertEqual([redemption.coins_para(p, P) for p in redemption.PORCENTAJES], [600, 700, 800, 900, 1000])
        opciones = redemption.opciones(890, P)
        self.assertEqual([o["porcentaje"] for o in opciones if o["alcanza"]], [30, 35, 40])
        self.assertEqual(redemption.faltan_para_minimo(500, P), 100)
        self.assertEqual(redemption.faltan_para_minimo(1200, P), 0)

    def test_parametros_configurables(self):
        p = Params({"coin_porcentaje": 0.1, "exp_basico": 60})
        self.assertEqual(redemption.coins_para(30, p), 300)
        self.assertEqual(scoring.exp_reto("basico", "correcto", 0, False, p), 60)
        with self.assertRaises(AttributeError):
            p.exp_basico = 1


class DominioTest(unittest.TestCase):
    def test_ejemplo_del_documento_sin_decaimiento(self):
        sin_decaimiento = Params({"dominio_decaimiento": 1})
        intentos = [("basico", 100), ("intermedio", 50), ("intermedio", 50)]
        self.assertEqual(mastery.dominio(intentos, sin_decaimiento), 60)

    def test_decaimiento_pesa_mas_lo_reciente_y_ventana_de_10(self):
        self.assertGreater(mastery.dominio([("basico", 0), ("basico", 100)], P), 50)
        self.assertEqual(mastery.dominio([("basico", 0)] * 30 + [("basico", 100)] * 10, P), 100)
        self.assertIsNone(mastery.dominio([], P))

    def test_estados(self):
        self.assertEqual(mastery.estado(None, "basico", "avanzado", False, P), "sin_datos")
        self.assertEqual(mastery.estado(49.9, "basico", "avanzado", False, P), "debil")
        self.assertEqual(mastery.estado(65, "basico", "avanzado", False, P), "en_progreso")
        # 85 at the maximum level without a long review is still "En progreso".
        self.assertEqual(mastery.estado(85, "avanzado", "avanzado", False, P), "en_progreso")
        self.assertEqual(mastery.estado(85, "intermedio", "avanzado", True, P), "en_progreso")
        self.assertEqual(mastery.estado(85, "avanzado", "avanzado", True, P), "dominado")


class NivelesTest(unittest.TestCase):
    def test_ajuste_dentro_del_quiz(self):
        self.assertEqual(levels.siguiente_en_quiz("basico", "avanzado", []), "basico")
        self.assertEqual(levels.siguiente_en_quiz("basico", "avanzado", [("basico", "correcto", 0)]), "intermedio")
        self.assertEqual(levels.siguiente_en_quiz("basico", "avanzado", [("basico", "correcto", 1)]), "basico")
        self.assertEqual(levels.siguiente_en_quiz("intermedio", "avanzado", [("intermedio", "incorrecto", 0)]), "intermedio")
        self.assertEqual(levels.siguiente_en_quiz("intermedio", "avanzado",
                                                  [("intermedio", "incorrecto", 0), ("intermedio", "incorrecto", 0)]), "basico")
        # Never above the topic maximum.
        self.assertEqual(levels.siguiente_en_quiz("intermedio", "intermedio", [("intermedio", "correcto", 0)]), "intermedio")

    def test_nivel_guardado_ultimos_5_con_minimo_3(self):
        self.assertEqual(levels.nivel_guardado("basico", "avanzado", [100, 100], P), "basico")
        self.assertEqual(levels.nivel_guardado("basico", "avanzado", [100, 100, 100], P), "intermedio")
        self.assertEqual(levels.nivel_guardado("intermedio", "avanzado", [0, 0, 50], P), "basico")
        self.assertEqual(levels.nivel_guardado("intermedio", "avanzado", [0, 100, 100, 100, 100, 50], P), "avanzado")
        self.assertEqual(levels.nivel_guardado("intermedio", "avanzado", [100, 50, 50], P), "intermedio")
        self.assertEqual(levels.nivel_guardado("avanzado", "intermedio", [], P), "intermedio")

    def test_version_mas_cercana(self):
        self.assertEqual(levels.mas_cercano("avanzado", ["basico", "intermedio"]), "intermedio")
        self.assertEqual(levels.mas_cercano("basico", ["intermedio", "maestria"]), "intermedio")
        self.assertIsNone(levels.mas_cercano("basico", []))


class RepasoTest(unittest.TestCase):
    def test_intervalos(self):
        actual, recorrido = 1, []
        for _ in range(6):
            actual = spacing.siguiente_intervalo(actual, "correcto", 0)
            recorrido.append(actual)
        self.assertEqual(recorrido, [3, 7, 14, 30, 30, 30])
        self.assertEqual(spacing.siguiente_intervalo(7, "correcto", 1), 7)
        self.assertEqual(spacing.siguiente_intervalo(14, "incorrecto", 0), 1)

    def test_semana_lima_cambia_el_lunes_a_las_00(self):
        domingo_noche = datetime(2026, 10, 12, 4, 59, tzinfo=timezone.utc)   # Sunday 23:59 in Lima
        lunes = datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc)            # Monday 00:00 in Lima
        self.assertEqual(semana_de(domingo_noche), date(2026, 10, 5))
        self.assertEqual(semana_de(lunes), date(2026, 10, 12))


class RiesgoYSeleccionTest(unittest.TestCase):
    def test_inactividad_y_caida(self):
        ahora = datetime(2026, 10, 13, tzinfo=timezone.utc)
        self.assertEqual(risk.senales(ahora - timedelta(days=4), ahora, None, None, ahora, P), [])
        tipos = [s["tipo"] for s in risk.senales(ahora - timedelta(days=5), ahora, 50, 70, ahora, P)]
        self.assertEqual(tipos, ["inactividad", "caida"])
        self.assertEqual(risk.senales(ahora, ahora, 56, 70, ahora, P), [])

    def test_retos_de_clase_priorizan_temas_debiles(self):
        retos = [{"id": 1, "posicion": 1, "tema_id": 10}, {"id": 2, "posicion": 2, "tema_id": 20},
                 {"id": 3, "posicion": 3, "tema_id": 30}, {"id": 4, "posicion": 4, "tema_id": 40}]
        elegidos, reserva = elegir_retos_clase(retos, {10: 95, 20: 40, 30: None, 40: 60})
        self.assertEqual([r["id"] for r in elegidos], [2, 3, 4])
        self.assertEqual([r["id"] for r in reserva], [1])

    def test_sorteo_semanal_es_igual_para_todos(self):
        temas = [{"id": i, "es_fundamental": i == 3, "vencidos": 0, "dominio": None} for i in range(1, 8)]
        self.assertEqual(sortear_tema(temas, "1:2026-10-12"), sortear_tema(temas, "1:2026-10-12"))
        self.assertNotEqual(sortear_tema(temas, "1:2026-10-12", excluir=5), 5)
