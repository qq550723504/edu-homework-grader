from ..db import SessionLocal
from ..models import utc_now
from ..routers.teacher import get_student_provisioner
from ..services.student_activations import expire_activations


def main() -> None:
    with SessionLocal() as session:
        expire_activations(session, keycloak=get_student_provisioner(), now=utc_now())


if __name__ == "__main__":
    main()
