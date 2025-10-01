from __future__ import annotations as _annotations

import logging

from fastapi import APIRouter
from fastui import AnyComponent, FastUI
from fastui.components.display import DisplayLookup, DisplayMode
from fastui.events import GoToEvent, BackEvent
from pydantic import BaseModel, Field
from datetime import date
from fastui import components as c
from pages.shared import demo_page

router = APIRouter()


class User(BaseModel):
    id: int = Field(title="ID")
    name: str = Field(title="Name")
    dob: date = Field(title="Date of Birth")
    enabled: bool | None = None
    status_markdown: str | None = Field(default=None, title="Status")


users: list[User] = [
    User(
        id=1,
        name="John",
        dob=date(1990, 1, 1),
        enabled=True,
        status_markdown="**Active**",
    ),
    User(
        id=2,
        name="Jane",
        dob=date(1991, 1, 1),
        enabled=False,
        status_markdown="*Inactive*",
    ),
    User(id=3, name="Jack", dob=date(1992, 1, 1)),
]


@router.get("/users", response_model=FastUI, response_model_exclude_none=True)
def users_view() -> AnyComponent:
    logging.info("users_view entered")
    return dict(
        # c.Page(  # Page provides a basic container for components
        (
            c.Heading(text="Users", level=2),  # renders `<h2>Users</h2>`
            # c.Table(
            #     data=users,
            #     # define two columns for the table
            #     columns=[
            #         # the first is the users, name rendered as a link to their profile
            #         DisplayLookup(
            #             field="name", on_click=GoToEvent(url="/user/{id}/")
            #         ),
            #         # the second is the date of birth, rendered as a date
            #         DisplayLookup(field="dob", mode=DisplayMode.date),
            #     ],
            # ),
        ),
        # ),
    )
    # return demo_page(
    #     *tabs(),
    #     c.Table(
    #         data=users,
    #         columns=[
    #             DisplayLookup(
    #                 field="name", on_click=GoToEvent(url="/table/users/{id}/")
    #             ),
    #             DisplayLookup(field="dob", mode=DisplayMode.date),
    #             DisplayLookup(field="enabled"),
    #             DisplayLookup(field="status_markdown", mode=DisplayMode.markdown),
    #         ],
    #     ),
    #     title="Users",
    # )


def tabs() -> list[AnyComponent]:  # AnyComponent]:
    return [
        c.LinkList(
            links=[
                c.Link(
                    components=[c.Text(text="Cities")],
                    on_click=GoToEvent(url="/table/cities"),
                    active="startswith:/table/cities",
                ),
                c.Link(
                    components=[c.Text(text="Users")],
                    on_click=GoToEvent(url="/table/users"),
                    active="startswith:/table/users",
                ),
            ],
            mode="tabs",
            class_name="+ mb-4",
        ),
    ]


@router.get("/users/{id}/", response_model=FastUI, response_model_exclude_none=True)
def user_profile(id: int) -> list[AnyComponent]:
    user: User | None = users[id - 1] if id <= len(users) else None
    return demo_page(
        *tabs(),
        c.Link(components=[c.Text(text="Back")], on_click=BackEvent()),
        c.Details(
            data=user,
            fields=[
                DisplayLookup(field="name"),
                DisplayLookup(field="dob", mode=DisplayMode.date),
                DisplayLookup(field="enabled"),
            ],
        ),
        title=user.name,
    )
