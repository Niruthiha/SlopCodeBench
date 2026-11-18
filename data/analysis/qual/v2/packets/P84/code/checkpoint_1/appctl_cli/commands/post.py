"""``appctl post``: post management (simulated)."""

from ..errors import AppctlError
from ._listing import LIST_OPTIONS, render_list, render_record

POSTS = [
    {"ID": 1, "post_title": "Hello world!", "post_name": "hello-world", "post_type": "post",
     "post_status": "publish", "post_author": 1},
    {"ID": 2, "post_title": "Sample Page", "post_name": "sample-page", "post_type": "page",
     "post_status": "publish", "post_author": 1},
    {"ID": 3, "post_title": "Draft idea", "post_name": "draft-idea", "post_type": "post",
     "post_status": "draft", "post_author": 2},
]
FIELDS = ["ID", "post_title", "post_name", "post_type", "post_status", "post_author"]
LIST_FIELDS = ["ID", "post_title", "post_name", "post_status"]


def _find(post_id):
    return next((p for p in POSTS if str(p["ID"]) == str(post_id)), None)


def create(ctx, args, assoc):
    new_id = max(p["ID"] for p in POSTS) + 1
    if assoc.get("porcelain"):
        ctx.output.line(str(new_id))
        return
    title = assoc.get("post_title") or "(no title)"
    ctx.output.success(
        f"Created post {new_id} ('{title}', type: {assoc['post_type']}, status: {assoc['post_status']})."
    )


def delete(ctx, args, assoc):
    verb = "Deleted" if assoc.get("force") else "Trashed"
    failed = 0
    for post_id in args:
        if _find(post_id):
            ctx.output.success(f"{verb} post {post_id}.")
        else:
            ctx.output.warning(f"Failed deleting post {post_id}.")
            failed += 1
    return 1 if failed else 0


def get(ctx, args, assoc):
    post = _find(args[0])
    if post is None:
        raise AppctlError(f"Could not find the post with ID {args[0]}.")
    render_record(ctx, post, assoc, FIELDS)


def list_(ctx, args, assoc):
    render_list(ctx, POSTS, assoc, LIST_FIELDS, FIELDS, id_field="ID")


def update(ctx, args, assoc):
    for post_id in args:
        if _find(post_id) is None:
            raise AppctlError(f"Could not find the post with ID {post_id}.")
        ctx.output.success(f"Updated post {post_id}.")


def register(registry):
    registry.add("post", description="Manages posts, content, and meta.")
    registry.add(
        "post create", create,
        synopsis="[--post_type=<type>] [--post_title=<title>] [--post_status=<status>] "
                 "[--post_content=<content>] [--<field>=<value>] [--porcelain]",
        description="Creates a new post.",
        defaults={"post_type": "post", "post_status": "draft"},
        options={"post_type": "The post type.", "post_title": "The title of the post.",
                 "post_status": "The post status.", "post_content": "The post content.",
                 "porcelain": "Output just the new post id."},
    )
    registry.add(
        "post delete", delete,
        synopsis="<id>... [--force]",
        description="Deletes an existing post.",
        options={"id": "One or more IDs of posts to delete.",
                 "force": "Skip the trash bin."},
    )
    registry.add(
        "post get", get,
        synopsis="<id> [--field=<field>] [--fields=<fields>] [--format=<format>]",
        description="Gets details about a post.",
        defaults={"format": "table"},
        options=dict(LIST_OPTIONS, id="The ID of the post to get."),
    )
    registry.add(
        "post list", list_,
        synopsis="[--<field>=<value>] [--field=<field>] [--fields=<fields>] [--format=<format>]",
        description="Gets a list of posts.",
        defaults={"format": "table"},
        options=LIST_OPTIONS,
    )
    registry.add(
        "post update", update,
        synopsis="<id>... [--<field>=<value>]",
        description="Updates one or more existing posts.",
        options={"id": "One or more IDs of posts to update."},
    )
