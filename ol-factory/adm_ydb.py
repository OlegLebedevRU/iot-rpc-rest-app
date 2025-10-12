# import ydb
# import ydb.iam
# token= "y0__xDM1cOGqveAAhjB3RMg9N7moRIIJekRpBCiFIW5hxjqN8NbhDvTeQ"
# # Create driver in global space.
# driver = ydb.Driver(
#   connection_string="grpcs://ydb.serverless.yandexcloud.net:2135/?database=/ru-central1/b1ggvoclbrs0okll36oa/etndq828u5vetj34t655",
#   #endpoint="grpcs://ydb.serverless.yandexcloud.net:2135",
#   #database="/ru-central1/b1ggvoclbrs0okll36oa/etndq828u5vetj34t655",
#   credentials=ydb.credentials.AccessTokenCredentials(token),
# )
# driver.wait(fail_fast=True, timeout=30)
# pool = ydb.SessionPool(driver)
#
# def execute_query(session):
#
#   # Create the transaction and execute query.
#   return session.transaction().execute(
#     'select 1 as cnt;',
#     commit_tx=True,
#     settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
#     )
# result = pool.retry_operation_sync(execute_query)
# print(str(result[0].rows[0].cnt == 1))

from tkinter import *
from tkinter import ttk

root = Tk()
root.title("METANIT.COM")
root.geometry("250x200")

# определяем данные для отображения
people = [("Tom", 38, "tom@email.com"), ("Bob", 42, "bob@email.com"), ("Sam", 28, "sam@email.com")]

label = ttk.Label()
label.pack(anchor=N, fill=X)
# определяем столбцы
columns = ("name", "age", "email")
tree = ttk.Treeview(columns=columns, show="headings")
tree.pack(expand=1, fill=BOTH)

# определяем заголовки
tree.heading("name", text="Имя", anchor=W)
tree.heading("age", text="Возраст", anchor=W)
tree.heading("email", text="Email", anchor=W)

tree.column("#1", stretch=NO, width=70)
tree.column("#2", stretch=NO, width=60)
tree.column("#3", stretch=NO, width=100)

# добавляем данные
for person in people:
  tree.insert("", END, values=person)


def item_selected(event):
  selected_people = ""
  for selected_item in tree.selection():
    item = tree.item(selected_item)
    person = item["values"]
    selected_people = f"{selected_people}{person}\n"
  label["text"] = selected_people


tree.bind("<<TreeviewSelect>>", item_selected)

root.mainloop()