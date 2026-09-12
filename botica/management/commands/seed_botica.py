"""Datos de demostración para la botica (catálogo + lotes con kardex).

Uso:
    uv run python manage.py seed_botica
    uv run python manage.py seed_botica --email usuario@outlook.com --password clave123

Es idempotente: los productos existentes (por código) se omiten.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from botica.models import Producto, User
from botica.services import registrar_entrada

# (codigo, nombre, principio_activo, concentracion, presentacion, laboratorio,
#  stock_minimo, precio_venta, precio_blister, precio_caja, costo,
#  uds/blister, blisters/caja, [(lote, venc_en_dias, stock)])
CATALOGO = [
    ("P0001", "Paracetamol", "Paracetamol", "500mg", "Tableta", "Medifarma",
     50, "0.40", "4.00", "40.00", "0.12", 10, 10,
     [("LT-P0455", 240, 320), ("LT-P0298", 90, 80)]),
    ("P0002", "Amoxicilina", "Amoxicilina", "500mg", "Cápsula", "ABL Pharma",
     30, "0.80", "7.50", None, "0.28", 10, 0,
     [("LT-X1207", 124, 96)]),
    ("P0003", "Ibuprofeno", "Ibuprofeno", "400mg", "Tableta", "Roe",
     40, "0.60", "5.50", None, "0.22", 10, 0,
     [("LT-I3308", 79, 310)]),
    ("P0004", "Omeprazol", "Omeprazol", "20mg", "Cápsula", "Quimofarm",
     25, "0.70", "4.20", "12.00", "0.25", 10, 10,
     [("LT-O4419", 54, 220)]),
    ("P0005", "Losartán", "Losartán potásico", "50mg", "Tableta", "Genfar",
     60, "0.50", None, "14.00", "0.18", 0, 20,
     [("LT-L0117", 6, 48)]),
    ("P0006", "Azitromicina", "Azitromicina", "500mg", "Tableta", "Pfizer",
     20, "1.80", None, None, "0.85", 0, 0,
     [("LT-A2311", -12, 12)]),
    ("P0008", "Vitamina C", "Ácido ascórbico", "1g", "Efervescente", "Bayer",
     30, "0.40", "5.40", None, "0.15", 10, 0,
     [("LT-V7741", 29, 140)]),
    # Combinado: la búsqueda por "paracetamol" también lo encuentra
    ("P0009", "Algidol", "Paracetamol + Cafeína + Fenilefrina", "500/65/10mg",
     "Cápsula", "Tecnoquímicas", 20, "0.90", "8.00", None, "0.30", 10, 0,
     [("LT-A5520", 150, 75)]),
     ("P9804", "Gloranta", "Propóleo + Miel", "N/A", "Sobre", "PORTUGAL", 
     20, "3.00", None, "64.90", "1.50", 1, 25, 
     [("20200120", 527, 85)]),
    
    ("P9198", "Azitromicina", "Azitromicina", "200mg/5ml", "Frasco", "PORTUGAL", 
     10, "8.00", None, None, "4.50", 0, 0, 
     [("2057806", 977, 40)]),
    
    ("P9055", "Dicloxacilina", "Dicloxacilina", "500mg", "Cápsula", "PORTUGAL", 
     30, "0.50", "4.50", "36.90", "0.20", 10, 10, 
     [("2036168", 532, 200)]),
    
    ("P8585", "Fluconazol", "Fluconazol", "150mg", "Cápsula", "PORTUGAL", 
     15, "0.50", "4.00", "27.10", "0.15", 10, 10, 
     [("2102885", 775, 150)]),
    
    ("P9021", "Glibenclamida", "Glibenclamida", "5mg", "Tableta", "PORTUGAL", 
     20, "0.10", "0.80", "4.50", "0.02", 10, 10, 
     [("2032018", 926, 300)]),
    
    ("P9022", "Guaifenesina", "Guaifenesina", "100mg/5ml", "Frasco", "PORTUGAL", 
     10, "5.00", None, None, "2.50", 0, 0, 
     [("2042736", 957, 35)]),
    
    ("P8313", "Losartán", "Losartán", "50mg", "Tableta", "IQFARMA", 
     25, "0.20", "1.50", "6.50", "0.05", 10, 6, 
     [("21000745", 775, 120)]),
    
    ("P8410", "Melatonina", "Melatonina", "3mg", "Tableta", "PORTUGAL", 
     10, "0.50", "4.50", "12.00", "0.20", 10, 3, 
     [("2023046", 527, 45)]),
    
    ("P8575", "Omeprazol", "Omeprazol", "20mg", "Cápsula", "PORTUGAL", 
     20, "0.20", "1.80", "14.50", "0.08", 10, 10, 
     [("2033626", 921, 250)]),
    
    ("P8272", "Terbinafina", "Terbinafina", "250mg", "Tableta", "PORTUGAL", 
     10, "0.50", "4.50", "35.00", "0.25", 10, 10, 
     [("2075975", 688, 90)]),
    
    ("P7947", "Ursocolik", "Ácido Ursodesoxicólico", "300mg", "Tableta", "INTIPHARMA", 
     5, "3.50", "32.00", "84.50", "2.00", 10, 3, 
     [("U-36001", 658, 20)]),
    
    ("P9173", "Clondicyn", "Clindamicina", "300mg", "Cápsula", "BONAPHARM", 
     15, "0.90", "8.50", "36.00", "0.50", 10, 5, 
     [("ME25K019", 374, 50)]),
    
    ("P9154", "Tretocheck 10", "Isotretinoína", "10mg", "Cápsula", "BONAPHARM", 
     10, "1.00", "9.00", "24.00", "0.60", 10, 3, 
     [("S2642360", 643, 30)]),
    
    ("P8886", "Metamizol Sódico", "Metamizol", "1g/2ml", "Ampolla", "DIPHASAC", 
     20, "1.00", None, "35.00", "0.40", 1, 50, 
     [("250962", 750, 100)]),
    
    ("P9142", "Sildenafilo", "Sildenafilo", "100mg", "Tableta", "IQFARMA", 
     50, "2.00", None, None, "0.60", 1, 1, 
     [("20302526", 932, 200)]),
    
    ("P9140", "Albendazol", "Albendazol", "100mg/5ml", "Frasco", "IQFARMA", 
     10, "3.50", None, None, "1.20", 0, 0, 
     [("20201454", 535, 60)]),
    
    ("P9191", "Cefalexina", "Cefalexina", "500mg", "Cápsula", "IQFARMA", 
     15, "0.50", "4.50", "36.00", "0.25", 10, 10, 
     [("20400756", 1317, 100)]),
    
    ("P8350", "Clindamicina", "Clindamicina", "300mg", "Cápsula", "IQFARMA", 
     10, "0.60", "5.00", "41.00", "0.30", 10, 10, 
     [("20301195", 556, 80)]),
    
    ("P9146", "Mupirocina", "Mupirocina", "2%", "Tubo", "IQFARMA", 
     5, "15.00", None, None, "8.00", 0, 0, 
     [("20501696", 987, 25)]),
    
    ("P9139", "Simeticona", "Simeticona", "80mg", "Tableta", "IQFARMA", 
     15, "0.40", "3.50", "8.50", "0.15", 10, 3, 
     [("20300936", 921, 60)]),
    
    ("P8814", "Fullgermina", "Probióticos", "2000 Mill. UFC", "Vial", "LAFARMED", 
     10, "1.50", None, "12.50", "0.80", 1, 10, 
     [("BCS11525", 351, 40)]),
    
    ("P8918", "Baby Test Junior", "HCG", "N/A", "Tira", "MONT", 
     20, "2.50", None, None, "0.70", 1, 1, 
     [("HCG2602", 872, 80)]),
    
    ("P9208", "Portil NF", "Clotrimazol + Gentamicina + Betametasona", "N/A", "Tubo", "PORTUGAL", 
     10, "4.50", None, None, "1.80", 0, 0, 
     [("2034646", 921, 35)]),
    
    ("P7903", "Welplex", "Levocetirizina + Fenilefrina", "10mg/100mg/5ml", "Frasco", "PORTUGAL", 
     10, "8.00", None, None, "4.00", 0, 0, 
     [("2096075", 750, 25)]),
    
    ("P8599", "Amoxicilina", "Amoxicilina", "250mg/5ml", "Frasco", "PORTUGAL", 
     10, "4.50", None, None, "2.00", 0, 0, 
     [("2095835", 740, 50)]),
    
    ("P7830", "Atorvastatina", "Atorvastatina", "10mg", "Tableta", "PORTUGAL", 
     15, "0.20", "1.50", "10.00", "0.06", 10, 10, 
     [("2073464", 317, 120)]),
    
    ("P8909", "Aciclovir", "Aciclovir", "800mg", "Tableta", "PORTUGAL", 
     10, "1.20", None, "9.50", "0.60", 10, 1, 
     [("20401778", 579, 45)]),
    
    ("P9111", "Zitrotrim", "Azitromicina", "200mg/5ml", "Frasco", "PORTUGAL", 
     10, "10.00", None, None, "5.00", 0, 0, 
     [("2016446", 857, 30)]),
    
    ("P8253", "Metglu", "Metformina", "850mg", "Tableta", "PORTUGAL", 
     20, "0.80", "7.00", "13.50", "0.40", 10, 2, 
     [("2018776", 496, 60)]),
    
    ("P8672", "Levoctrim Forte", "Levofloxacino", "750mg", "Tableta", "PORTUGAL", 
     10, "1.50", None, "8.00", "0.70", 7, 1, 
     [("2027316", 527, 25)]),
    
    ("P8224", "Levoctrim", "Levofloxacino", "500mg", "Tableta", "PORTUGAL", 
     10, "0.80", None, "6.50", "0.35", 10, 1, 
     [("2017806", 867, 35)]),
    
    ("P8796", "Gastrolud", "Esomeprazol", "40mg", "Tableta", "PORTUGAL", 
     10, "0.70", "6.00", "16.50", "0.35", 10, 3, 
     [("2027776", 532, 40)]),
    
    ("P9003", "Desazona", "Dexametasona", "4mg", "Tableta", "PORTUGAL", 
     15, "0.20", "1.50", "10.50", "0.06", 10, 10, 
     [("2029456", 893, 100)]),
    
    ("P9000", "Broncodilat Adulto", "Salbutamol", "N/A", "Frasco", "PORTUGAL", 
     10, "13.50", None, None, "7.00", 0, 0, 
     [("2022956", 893, 30)]),
    
    ("P7801", "Broncotrin Dilat", "Salbutamol", "N/A", "Frasco", "PORTUGAL", 
     10, "9.00", None, None, "4.50", 0, 0, 
     [("2124835", 465, 30)]),
    
    ("P8541", "Bexaderm", "Betametasona + Gentamicina", "N/A", "Tubo", "PORTUGAL", 
     10, "6.00", None, None, "2.50", 0, 0, 
     [("2019886", 857, 45)]),
    
    ("P9017", "Arcodex", "Desloratadina", "120mg", "Tableta", "PORTUGAL", 
     5, "1.50", None, "9.50", "0.80", 7, 1, 
     [("2018406", 496, 25)])
]


class Command(BaseCommand):
    help = "Carga el catálogo de demostración con lotes y movimientos de entrada."

    def add_arguments(self, parser):
        parser.add_argument("--email", help="Crear usuario de cabina con este email")
        parser.add_argument("--password", help="Contraseña del usuario de cabina")

    def handle(self, *args, **options):
        hoy = timezone.localdate()
        creados = 0
        for (codigo, nombre, pa, conc, pres, lab, stock_min, p_venta,
             p_blis, p_caja, costo, upb, bpc, lotes) in CATALOGO:
            producto, nuevo = Producto.objects.get_or_create(
                codigo=codigo,
                defaults={
                    "nombre": nombre,
                    "principio_activo": pa,
                    "concentracion": conc,
                    "presentacion": pres,
                    "laboratorio": lab,
                    "stock_minimo": stock_min,
                    "precio_venta": Decimal(p_venta),
                    "precio_blister": Decimal(p_blis) if p_blis else None,
                    "precio_caja": Decimal(p_caja) if p_caja else None,
                    "costo_unitario": Decimal(costo),
                    "unidades_por_blister": upb,
                    "blisters_por_caja": bpc,
                },
            )
            if not nuevo:
                self.stdout.write(f"  · {codigo} ya existe, omitido")
                continue
            creados += 1
            for codigo_lote, dias, stock in lotes:
                registrar_entrada(
                    producto=producto,
                    codigo_lote=codigo_lote,
                    fecha_vencimiento=hoy + timedelta(days=dias),
                    cantidad=stock,
                    costo_unitario=Decimal(costo),
                    motivo="Saldo inicial · carga de demostración",
                )
            self.stdout.write(f"  + {codigo} {nombre} ({len(lotes)} lote(s))")

        if options["email"]:
            if not options["password"]:
                self.stderr.write("Falta --password para crear el usuario.")
                return
            user, nuevo = User.objects.get_or_create(
                email=options["email"].lower(),
                defaults={"nombre": "Caja 01"},
            )
            if nuevo:
                user.set_password(options["password"])
                user.save()
                self.stdout.write(f"  + usuario {user.email} creado")
            else:
                self.stdout.write(f"  · usuario {user.email} ya existe")

        self.stdout.write(self.style.SUCCESS(
            f"Listo: {creados} productos nuevos con sus lotes y kardex."
        ))
