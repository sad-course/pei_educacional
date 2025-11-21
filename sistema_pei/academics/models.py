from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import ProtectedError
from django.forms.models import model_to_dict
from django.utils.translation import gettext_lazy as _

from sistema_pei.academics import managers
from sistema_pei.academics.constants import COURSE_TYPE
from sistema_pei.core.constants import SMALL_CHAR_FIELD_NAME_LENGTH
from sistema_pei.core.models import BaseModel
from sistema_pei.people.models import Teacher


# Create your models here.
class Course(BaseModel):
    class CoursePeriod(models.TextChoices):
        MORNING = "MORNING", _("Matutino")
        AFTERNOON = "AFTERNOON", _("Vespertino")
        NIGHT = "NIGHT", _("Noturno")

    class CourseDurationType(models.TextChoices):
        SEMESTER = "SEMESTER", _("Semestral")
        YEAR = "YEAR", _("Anual")

    name = models.CharField(max_length=80, verbose_name=_("Nome"))
    course_type = models.CharField(
        max_length=55,
        choices=COURSE_TYPE,
        verbose_name=_("Tipo"),
    )
    period = models.CharField(
        max_length=15,
        choices=CoursePeriod.choices,
        verbose_name=_("Turno"),
    )

    duration_type = models.CharField(
        choices=CourseDurationType.choices,
        verbose_name=_("Tipo de duração"),
    )

    number_of_periods = models.PositiveSmallIntegerField(
        verbose_name=_("Número de períodos/Anos"),
        validators=[
            MinValueValidator(1),
        ],
    )

    class Meta:
        verbose_name = _("Curso")
        verbose_name_plural = _("Cursos")

    def __str__(self):
        return self.name + " - " + self.get_period_display()


class Subject(BaseModel):
    class SubjectsDuration(models.TextChoices):
        SEMESTER = "SEMESTER", _("Semestral")
        YEAR = "YEAR", _("Anual")

    name = models.CharField(max_length=100)
    matrix = models.ForeignKey(
        verbose_name=_("Matriz da disciplina"),
        to="academics.Matrix",
        related_name="subjects",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
    )
    subject_type = models.CharField(
        max_length=15,
        choices=SubjectsDuration.choices,
        verbose_name=_("Duração"),
    )
    courses = models.ManyToManyField(
        Course,
        verbose_name=_("Cursos"),
        related_name="subjects",
    )
    objective = models.TextField(
        verbose_name=_("Objetivos"),
        blank=True,
    )
    content = models.TextField(
        verbose_name=_("Conteúdo"),
        blank=True,
    )
    methodology = models.TextField(
        verbose_name=_("Metodologia"),
        blank=True,
    )
    resources = models.TextField(
        verbose_name=("Recursos"),
        blank=True,
    )
    assessments = models.TextField(
        verbose_name=_("Avaliações"),
        blank=True,
    )

    class Meta:
        verbose_name = _("Disciplina")
        verbose_name_plural = _("Disciplinas")

    def __str__(self):
        return self.name

    def is_filled(self):
        return len(self.get_fields_not_filled()) == 0

    def get_fields_not_filled(self):
        data = model_to_dict(
            self,
            fields=["objective", "content", "methodology", "resources", "assessments"],
        )
        return [field for field, value in data.items() if not value]


class Offer(BaseModel):
    class OfferStatus(models.TextChoices):
        OPEN = "Aberta", "Aberta"
        CLOSED = "Fechada", "Fechada"

    class Semester(models.IntegerChoices):
        FIRST = 1, _("1º Semestre")
        SECOND = 2, _("2º Semestre")

    status = models.CharField(
        verbose_name=_("Situação"),
        max_length=SMALL_CHAR_FIELD_NAME_LENGTH,
        choices=OfferStatus.choices,
        default=OfferStatus.OPEN,
    )
    subject = models.ForeignKey(
        Subject,
        verbose_name=_("Disciplina"),
        on_delete=models.PROTECT,
        related_name="offers",
    )
    course = models.ForeignKey(
        Course,
        verbose_name=_("Curso"),
        on_delete=models.PROTECT,
        related_name="courses",
    )
    teachers = models.ManyToManyField(
        Teacher,
        verbose_name=_("Professor"),
        related_name="offers",
    )

    year = models.PositiveSmallIntegerField(
        verbose_name=_("Ano referência do período letivo"),
    )
    semester = models.PositiveSmallIntegerField(
        verbose_name=_("Semestre referência do período letivo"),
        choices=Semester.choices,
    )

    objects = managers.OfferManager()

    class Meta:
        verbose_name = _("Oferta")
        verbose_name_plural = _("Ofertas")

    def student_count(self):
        return self.enrollments.count()

    def available_students(self):
        """
        Retorna alunos disponíveis para inclusão que ainda não estão
        matriculados nesta oferta.
        """
        Student = apps.get_model("people", "Student")
        return Student.objects.filter(course=self.course).exclude(
            id__in=self.enrollments.values_list("student_id", flat=True),
        )

    def add_student(self, student, user):
        """Adiciona um aluno à oferta. Levanta ValidationError se não for possível."""
        if self.status != Offer.OfferStatus.OPEN:
            raise ValidationError(
                _("Não é possível adicionar alunos em uma oferta fechada."),
            )

        Enrollment = apps.get_model("academics", "Enrollment")
        if Enrollment.objects.filter(offer=self, student=student).exists():
            raise ValidationError(_("Aluno já matriculado nesta oferta."))

        return Enrollment.objects.create(
            offer=self,
            student=student,
            YearSemesterReference=student.reference_period,
            created_by=user,
            updated_by=user,
        )

    def remove_student(self, student):
        """
        Remove um aluno da oferta, excluindo também PEIs associados.
        Levanta ValidationError se não for possível.
        """
        Enrollment = apps.get_model("academics", "Enrollment")
        Pei = apps.get_model("educational_plan", "Pei")

        enrollment = Enrollment.objects.filter(offer=self, student=student).first()
        if not enrollment:
            raise ValidationError(_("Este discente não está matriculado nesta oferta."))

        try:
            Pei.objects.filter(enrollment=enrollment).delete()
            enrollment.delete()
        except ProtectedError as err:
            raise ValidationError(
                _(
                    "Não é possível remover o discente desta oferta "
                    "pois existem PEIs associados.",
                ),
            ) from err

        return True

    def __str__(self):
        return self.subject.name


class Enrollment(BaseModel):
    offer = models.ForeignKey(
        Offer,
        verbose_name=_("Oferta"),
        on_delete=models.PROTECT,
        related_name="enrollments",
    )
    student = models.ForeignKey(
        "people.Student",
        verbose_name=_("Aluno"),
        on_delete=models.PROTECT,
    )
    last_synced_at = models.DateTimeField(
        "Última Sincronização",
        null=True,
        blank=True,
    )
    grade1 = models.DecimalField(
        verbose_name=_("1 - Bimestre"),
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(0.00),
            MaxValueValidator(100.00)
        ],
    )
    absences1 = models.PositiveIntegerField(
        verbose_name=_("Faltas 1 Bimestre"),
        default=0,
    )
    grade2 = models.DecimalField(
        verbose_name=_("2 - Bimestre"),
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(0.00),
            MaxValueValidator(100.00)
        ],
    )
    absences2 = models.PositiveIntegerField(
        verbose_name=_("Faltas 2 Bimestre"),
        default=0,
    )
    grade3 = models.DecimalField(
        verbose_name=_("3 - Bimestre"),
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(0.00),
            MaxValueValidator(100.00)
        ],
    )
    absences3 = models.PositiveIntegerField(
        verbose_name=_("Faltas 3 Bimestre"),
        default=0,
    )
    grade4 = models.DecimalField(
        verbose_name=_("4 - Bimestre"),
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(0.00),
            MaxValueValidator(100.00)
        ],
    )
    absences4 = models.PositiveIntegerField(
        verbose_name=_("Faltas 4 Bimestre"),
        default=0,
    )

    YearSemesterReference = models.IntegerField(_("Cursado no semestre/ano do curso"))

    class Meta:
        unique_together = ("offer", "student")
        verbose_name = _("Inscrição")
        verbose_name_plural = _("Inscrições")

    def calcular_media(self):
        pass

    def __str__(self):
        return f"{self.student} - {self.offer.subject.name}"


class Matrix(BaseModel):
    code = models.IntegerField(
        verbose_name=_("Código da matriz"),
        unique=True,
        null=False,
        blank=False,
        validators=[MinValueValidator(1)],
    )

    description = models.CharField(
        verbose_name=_("Descrição da matriz"),
        null=False,
        blank=False,
    )

    year = models.IntegerField(
        verbose_name=_("Ano da matriz"),
        null=False,
        blank=False,
    )

    active = models.BooleanField(
        verbose_name=_("Ativa"),
        default=True,
    )

    def __str__(self):
        return f"{self.code} - {self.description}"

    class Meta:
        verbose_name = _("Matriz")
        verbose_name_plural = _("Matrizes")
        ordering = ["-year"]
